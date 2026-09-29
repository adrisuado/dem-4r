from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass,asdict
from pathlib import Path
import csv
import threading
from dem_tool.core.models import Project, Workflow, safe_name, atomic_json
from dem_tool.core.pipeline import Pipeline
import rasterio
import geopandas as gpd


@dataclass
class BatchItem:
    dem: str
    mask: str = ''


def import_csv(path):
    path=Path(path)
    def resolve(p): return str((path.parent/p).resolve()) if p else ''
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or 'dem' not in reader.fieldnames:
            raise ValueError('CSV requiere columnas dem y opcionalmente mask.')
        return [BatchItem(resolve(r['dem']),resolve(r.get('mask',''))) for r in reader]


def validate_batch(items,workflow):
    messages=[]
    needs_mask=any('$mask' in n.inputs.values() for n in workflow.nodes if n.enabled)
    for i,item in enumerate(items):
        try:
            with rasterio.open(item.dem) as src:
                if src.count!=1 or not src.crs: raise ValueError('DEM debe tener una banda y CRS.')
            if needs_mask and not item.mask: raise ValueError('El workflow requiere una máscara.')
            if item.mask:
                gdf=gpd.read_file(item.mask)
                if gdf.empty or not gdf.crs: raise ValueError('Máscara vacía o sin CRS.')
            messages.append((i,True,'Validado'))
        except Exception as exc:
            messages.append((i,False,str(exc)))
    return messages


class BatchProcessor:
    def __init__(self,workflow,root,workers=1,cancel=None,on_event=None,vertical_unit='m',sources=None,output_directory=None):
        self.workflow=workflow
        self.root=Path(root)
        self.workers=max(1,min(int(workers),8))
        self.cancel=cancel or threading.Event()
        self.on_event=on_event or (lambda *args:None)
        self.vertical_unit=vertical_unit
        self.sources=dict(sources or {})
        self.output_directory=Path(output_directory).resolve() if output_directory else None

    def run(self,items):
        self.root.mkdir(parents=True,exist_ok=True)
        outcomes={}
        def one(i,item):
            if self.cancel.is_set(): return {'status':'Cancelled'}
            root=self.root/f'{i+1:03d}_{safe_name(Path(item.dem).stem)}'
            sources=self.sources|{'$dem':item.dem}
            if item.mask: sources['$mask']=item.mask
            output=str(self.output_directory/root.name) if self.output_directory else None
            project=Project(root,Workflow.from_dict(asdict(self.workflow)),sources,vertical_unit=self.vertical_unit,output_directory=output)
            project.save()
            try:
                report=Pipeline(project,self.cancel,lambda n,s,m:self.on_event(i,n,s,m)).run()
                project.layers=list(report.results.values()); project.save()
                status='Error' if report.errors else 'Cancelled' if self.cancel.is_set() else 'Completed'
                return {'status':status,'errors':report.errors,'output':str(project.output_root),'project':str(root),'exports':report.exports}
            except Exception as exc:
                self.on_event(i,'','Error',str(exc))
                return {'status':'Error','errors':{'validation':str(exc)},'output':str(root)}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures={pool.submit(one,i,item):i for i,item in enumerate(items)}
            for future in as_completed(futures): outcomes[futures[future]]=future.result()
        atomic_json(self.root/'batch_report.json',outcomes)
        return outcomes
