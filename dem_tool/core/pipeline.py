from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import importlib.metadata
import json
import shutil
import threading
import time
import uuid

from dem_tool import __version__
from dem_tool.algorithms import load_algorithms
from dem_tool.algorithms.registry import Context, Cancelled
from dem_tool.core.models import Layer, Project, atomic_json, safe_name
from dem_tool.io.raster_io import spatial_info,read_raster,write_raster
import rasterio


def digest_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(layer):
    path=Path(layer.path)
    files=[path]
    if path.suffix.lower()=='.shp':
        files=sorted(path.parent.glob(path.stem+'.*'))
    else:
        files.extend(p for p in (Path(str(path)+'.msk'),Path(str(path)+'.aux.xml')) if p.exists())
    return {'files':[(p.name,digest_file(p)) for p in files], 'metadata':layer.metadata,'kind':layer.kind}


@dataclass
class RunReport:
    results: dict[str,Layer] = field(default_factory=dict)
    statuses: dict[str,str] = field(default_factory=dict)
    errors: dict[str,str] = field(default_factory=dict)
    cache_hits: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    log: str = ''


class Pipeline:
    def __init__(self,project:Project,cancel=None,on_event=None):
        self.project=project
        self.cancel=cancel or threading.Event()
        self.on_event=on_event or (lambda *args:None)
        self.registry=load_algorithms()
        self.versions={'dem-tool':__version__}
        for package in ('numpy','scipy','rasterio','geopandas','pysheds','pyproj'):
            self.versions[package]=importlib.metadata.version(package)
        self.versions['gdal']=rasterio.__gdal_version__
        # Invalidate caches after local source edits, even before a release version bump.
        root=Path(__file__).parents[1]
        self.versions['source_sha256']=hashlib.sha256(''.join(digest_file(p) for p in sorted(root.rglob('*.py'))).encode()).hexdigest()

    def validate(self,sources):
        ordered=self.project.workflow.ordered()
        types={k:v.kind for k,v in sources.items()}
        for key,layer in sources.items():
            if not Path(layer.path).is_file():
                raise ValueError(f'Entrada {key} no encontrada: {layer.path}')
        for node in ordered:
            if node.algorithm not in self.registry:
                raise ValueError(f'Algoritmo desconocido: {node.algorithm}')
            algorithm=self.registry[node.algorithm]
            unknown_params=set(node.parameters)-algorithm.defaults.keys()
            if unknown_params:
                raise ValueError(f'{node.name}: parámetros desconocidos {unknown_params}.')
            if node.enabled:
                if set(algorithm.ports)-node.inputs.keys():
                    raise ValueError(f'{node.name}: faltan conexiones {set(algorithm.ports)-node.inputs.keys()}.')
                unknown=set(node.inputs)-algorithm.ports.keys()-algorithm.optional_ports.keys()
                if node.algorithm=='calculator': unknown -= {'B'}
                if unknown:
                    raise ValueError(f'{node.name}: puertos desconocidos {unknown}.')
                for port,ref in node.inputs.items():
                    if ref not in types:
                        raise ValueError(f'{node.name}: entrada {ref} no disponible.')
                    expected=(algorithm.ports|algorithm.optional_ports).get(port,'raster')
                    if types[ref]!=expected and expected!='any':
                        raise ValueError(f'{node.name}: {port} requiere {expected}.')
            types[node.id]=algorithm.output
        return ordered

    def run(self,sources=None):
        project=self.project
        sources=sources or {k:Layer(v,kind='vector' if Path(v).suffix.lower() in ('.gpkg','.shp','.geojson') else 'raster',temporary=False,
                                   metadata={'vertical_unit':project.vertical_unit} if k=='$dem' else {}) for k,v in project.sources.items()}
        used={ref for n in project.workflow.nodes if n.enabled for ref in n.inputs.values() if ref.startswith('$')}
        sources={k:v for k,v in sources.items() if k in used}
        report=RunReport()
        run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]
        log=project.root/'logs'/f'{run_id}.jsonl'
        report.log=str(log)
        try:
            ordered=self.validate(sources)
        except Exception as exc:
            log.write_text(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),'run_id':run_id,
                'status':'Error','stage':'validation','message':str(exc),'sources':{k:v.path for k,v in sources.items()}},ensure_ascii=False)+'\n',encoding='utf-8')
            raise
        available=dict(sources)
        terminal=project.workflow.terminal_ids()
        hashes={k:fingerprint(v) for k,v in sources.items()}
        def event(node,status,message='',**extra):
            report.statuses[node.id]=status
            record={'timestamp':datetime.now(timezone.utc).isoformat(),'run_id':run_id,
                    'node':node.id,'name':node.name,'algorithm':node.algorithm,'status':status,'message':message,**extra}
            with log.open('a',encoding='utf-8') as f:
                f.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
            self.on_event(node.id,status,message)
        for node in ordered:
            if self.cancel.is_set():
                event(node,'Cancelled'); continue
            if not node.enabled or any(ref not in available for ref in node.inputs.values()):
                event(node,'Blocked','Nodo desactivado o dependencia no disponible.'); continue
            start=time.perf_counter()
            algorithm=self.registry[node.algorithm]
            inputs={port:available[ref] for port,ref in node.inputs.items()}
            params=algorithm.defaults|node.parameters
            event(node,'Running')
            directory=None
            try:
                key_data={'algorithm':algorithm.id,'parameters':params,
                          'output_dtype':node.output_dtype,'output_nodata':node.output_nodata,
                          'inputs':{k:hashes[r] for k,r in node.inputs.items()},'versions':self.versions,
                          'vertical_unit':project.vertical_unit}
                key=hashlib.sha256(json.dumps(key_data,sort_keys=True,allow_nan=False).encode()).hexdigest()
                directory=project.root/'temporary'/key
                manifest=directory/'complete.json'
                cached=None
                if manifest.exists():
                    d=json.loads(manifest.read_text(encoding='utf-8'))
                    if all(Path(p).is_file() and digest_file(p)==h for p,h in d['files'].items()):
                        cached=Layer(**d['layer'])
                if cached:
                    result=cached
                    report.cache_hits.append(node.id)
                    warnings=result.metadata.get('warnings',[])
                    result.metadata=result.metadata|{'inputs':{k:v.path for k,v in inputs.items()},'cache_reused_at':datetime.now(timezone.utc).isoformat()}
                else:
                    directory.mkdir(parents=True,exist_ok=True)
                    # Remove only incomplete files within this exact content-addressed cache entry.
                    for old in directory.iterdir():
                        if old.is_file(): old.unlink()
                    ctx=Context(directory,self.cancel,project.vertical_unit)
                    result=algorithm.run(inputs,node.parameters,ctx)
                    ctx.check()
                    if result.kind=='raster' and (node.output_dtype!='float64' or node.output_nodata is not None):
                        with rasterio.open(result.path) as src:
                            import numpy as np
                            data=src.read(masked=True).astype(float).filled(np.nan)
                            profile=src.profile.copy()
                        if data.shape[0]==1:data=data[0]
                        write_raster(result.path,data,profile,result.metadata,node.output_dtype,node.output_nodata)
                    warnings=ctx.warnings
                    spatial={}
                    if result.kind=='raster':
                        with rasterio.open(result.path) as raster:
                            try: spatial=spatial_info(raster.profile)
                            except ValueError: spatial={'crs':None}
                    result.metadata.update({'algorithm':algorithm.id,'parameters':params,
                        'inputs':{k:v.path for k,v in inputs.items()},'engine':algorithm.engine,
                        'libraries':self.versions,'timestamp':datetime.now(timezone.utc).isoformat(),
                        'duration_seconds':time.perf_counter()-start,'warnings':warnings,
                        'input_vertical_unit':project.vertical_unit,**spatial})
                    if result.kind=='raster':
                        result.metadata.update(output_dtype=node.output_dtype,output_nodata=node.output_nodata)
                    atomic_json(Path(result.path).with_suffix('.json'),result.metadata)
                    artifacts={str(p):digest_file(p) for p in directory.iterdir() if p.is_file() and p.name!='complete.json'}
                    atomic_json(manifest,{'layer':asdict(result),'files':artifacts})
                result.name=node.name
                result.temporary=True
                available[node.id]=result
                hashes[node.id]={'cache_key':key}
                report.results[node.id]=result
                do_export=(node.export=='always' or (node.export=='inherit' and
                           (project.workflow.export_policy=='detailed' or
                            (project.workflow.export_policy=='final' and node.id in terminal))))
                if do_export:
                    self.export_result(result,node,run_id,report)
                event(node,'Warning' if warnings else 'Completed','; '.join(warnings),
                      cache_hit=node.id in report.cache_hits,duration_seconds=time.perf_counter()-start,
                      output=result.path,metadata=result.metadata)
            except Cancelled:
                event(node,'Cancelled')
            except Exception as exc:
                report.errors[node.id]=str(exc)
                event(node,'Error',str(exc),parameters=params,inputs={k:v.path for k,v in inputs.items()},
                      libraries=self.versions,duration_seconds=time.perf_counter()-start)
        return report

    def export_result(self,result,node,run_id,report):
        category='vectors' if result.kind=='vector' else 'tables' if result.kind=='table' else self.registry[node.algorithm].category
        if category not in ('vectors','tables','hydrology'): category='relief'
        folder=self.project.root/category/run_id
        folder.mkdir(parents=True,exist_ok=True)
        source=Path(self.project.sources.get('$dem','DEM')).stem
        w=self.project.workflow
        name=safe_name(f'{w.prefix}{source}_{node.name}{w.suffix}')+'_'+safe_name(node.id)
        path=folder/(name+Path(result.path).suffix)
        shutil.copy2(result.path,path)
        if Path(result.path+'.msk').exists(): shutil.copy2(result.path+'.msk',str(path)+'.msk')
        extras=[]
        for extra in result.metadata.get('artifacts',[]):
            original=Path(extra)
            dst=folder/(name+'_'+original.name)
            shutil.copy2(original,dst)
            extras.append(str(dst))
        atomic_json(path.with_suffix('.json'),result.metadata|{'artifacts':extras})
        report.exports.extend([str(path),*extras])


def export_layer(layer,path):
    path=Path(path)
    if path.resolve()==Path(layer.path).resolve():
        raise ValueError('Seleccione una ruta diferente al archivo de origen.')
    path.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(layer.path,path)
    if Path(layer.path+'.msk').exists(): shutil.copy2(layer.path+'.msk',str(path)+'.msk')
    extras=[]
    for extra in layer.metadata.get('artifacts',[]):
        source=Path(extra)
        target=path.parent/(path.stem+'_'+source.name)
        if target.resolve()!=source.resolve():shutil.copy2(source,target)
        extras.append(str(target))
    atomic_json(path.with_suffix('.json'),layer.metadata|{'artifacts':extras})
