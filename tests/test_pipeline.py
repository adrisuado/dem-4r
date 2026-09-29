from dataclasses import asdict
from pathlib import Path
import threading
import numpy as np
import pytest
import geopandas as gpd
from shapely.geometry import box
from dem_tool.core.models import Project,Workflow,ProcessingNode as Node,Layer
from dem_tool.core.pipeline import Pipeline
from dem_tool.core.templates import relief_template
from dem_tool.batch.batch_processor import BatchProcessor,BatchItem,import_csv,validate_batch
from dem_tool.io.raster_io import read_raster,write_raster,StatisticsCache


def test_cycle_and_unknown_dependency():
    with pytest.raises(ValueError,match='ciclo'):
        Workflow(nodes=[Node('smooth',id='a',inputs={'dem':'b'}),Node('smooth',id='b',inputs={'dem':'a'})]).ordered()
    with pytest.raises(ValueError,match='inexistente'):
        Workflow(nodes=[Node('smooth',inputs={'dem':'missing'})]).ordered()


def test_acceptance_relief_cache_exports_and_reload(tmp_path,dem):
    w=relief_template('EPSG:32718',[300020,8699240,300480,8699960]); w.nodes[7].parameters={'radius':40,'unit':'meters'}
    project=Project(tmp_path/'relief',w,{'$dem':dem[0]}); run=Pipeline(project).run()
    assert not run.errors,run.errors
    assert len(run.results)==9 and len(run.exports)==3
    assert len(gpd.read_file(run.results['dissolve'].path))>=1
    assert read_raster(run.results['slope'].path)[0].shape==(36,46)
    rerun=Pipeline(project).run(); assert len(rerun.cache_hits)==9
    w.nodes[3].parameters={'units':'percent'}
    changed=Pipeline(project).run(); assert not changed.errors
    assert set(changed.cache_hits)=={'reproject','clip','smooth','tpi','curvature'}
    project.layers=list(changed.results.values()); project.layers[0].style.ramp='magma'; project.save()
    restored=Project.load(project.root/'project.json'); assert restored.layers[0].style.ramp=='magma'
    assert len(Pipeline(restored).run().cache_hits)==9
    w.save(project.root/'workflows'/'relief.json'); assert asdict(Workflow.load(project.root/'workflows'/'relief.json'))==asdict(w)


def test_cache_detects_modified_file_and_corrupt_output(tmp_path,dem):
    w=Workflow(nodes=[Node('smooth',id='s')]); p=Project(tmp_path/'p',w,{'$dem':dem[0]})
    r=Pipeline(p).run(); assert not r.cache_hits
    Path(r.results['s'].path).write_bytes(b'corrupt')
    r=Pipeline(p).run(); assert not r.errors and not r.cache_hits
    write_raster(dem[0],dem[1]+1,dem[2]); r=Pipeline(p).run(); assert not r.cache_hits


def test_disabled_block_cancel_policies(tmp_path,dem):
    w=Workflow(nodes=[Node('smooth',id='a',enabled=False),Node('slope',id='b',inputs={'dem':'a'})])
    p=Project(tmp_path/'p',w,{'$dem':dem[0]}); r=Pipeline(p).run(); assert set(r.statuses.values())=={'Blocked'}
    w.nodes[0].enabled=True; cancel=threading.Event(); cancel.set(); r=Pipeline(p,cancel).run(); assert set(r.statuses.values())=={'Cancelled'}
    w.export_policy='none'; w.nodes[0].export='always'; r=Pipeline(p).run(); assert len(r.exports)==1
    w.export_policy='detailed'; w.nodes[0].export='temporary'; r=Pipeline(p).run(); assert len(r.exports)==1


def test_clip_mask_reproject_and_buffer(tmp_path,dem,run_algorithm):
    mask=tmp_path/'mask.gpkg'; gpd.GeoDataFrame({'id':[1]},geometry=[box(300020,8699300,300200,8699800)],crs='EPSG:32718').to_file(mask,driver='GPKG')
    result=run_algorithm('clip_mask',inputs={'dem':Layer(dem[0]),'mask':Layer(str(mask),kind='vector')})
    a,p=read_raster(result.path); assert a.shape==(25,18)
    result=run_algorithm('reproject',{'crs':'EPSG:32718','resolution':20})
    assert read_raster(result.path)[0].shape==(40,25)
    b=run_algorithm('buffer',{'distance_m':10},{'vector':Layer(str(mask),kind='vector')})
    assert gpd.read_file(b.path).area.iloc[0]>gpd.read_file(mask).area.iloc[0]


def test_batch_reuses_workflow_and_isolates_same_names(tmp_path,dem):
    w=Workflow(nodes=[Node('slope',id='s')]); items=[BatchItem(dem[0]),BatchItem(dem[0])]
    outcomes=BatchProcessor(w,tmp_path/'batch',workers=2).run(items)
    assert all(o['status']=='Completed' for o in outcomes.values()),outcomes
    assert outcomes[0]['output']!=outcomes[1]['output']
    assert all(o['exports'] for o in outcomes.values())
    source=tmp_path/'batch.csv'; source.write_text('dem,mask\ndem.tif,\n',encoding='utf-8')
    assert import_csv(source)[0].dem==dem[0]
    assert validate_batch(import_csv(source),w)[0][1]


def test_statistics_counts_and_cache(dem):
    c=StatisticsCache(); first=c.get(dem[0],20); second=c.get(dem[0],20)
    assert first is second and first[0]['valid_pixels']==2000 and first[1][0].sum()==2000


def test_output_types_and_sentinel_collision(tmp_path,dem):
    import rasterio
    node=Node('slope',id='s',output_dtype='float32',output_nodata=-9999)
    p=Project(tmp_path/'typed',Workflow(nodes=[node]),{'$dem':dem[0]})
    r=Pipeline(p).run(); assert not r.errors
    with rasterio.open(r.results['s'].path) as src:
        assert src.dtypes==('float32',) and src.nodata==-9999
    node.output_dtype='int32'; r=Pipeline(p).run(); assert 'perdería' in r.errors['s']
    node.algorithm='calculator'; node.inputs={'A':'$dem'}; node.parameters={'expression':'A - A'}; node.output_nodata=0
    r=Pipeline(p).run(); assert 'coincide' in r.errors['s']


def test_failure_blocks_descendants_but_not_siblings(tmp_path,dem):
    w=Workflow(nodes=[Node('smooth',id='bad',parameters={'kernel':4}),Node('slope',id='blocked',inputs={'dem':'bad'}),Node('tpi',id='ok')])
    r=Pipeline(Project(tmp_path/'errors',w,{'$dem':dem[0]})).run()
    assert r.statuses['bad']=='Error' and r.statuses['blocked']=='Blocked' and r.statuses['ok']=='Completed'


def test_cache_ignores_symbology(tmp_path,dem):
    w=Workflow(nodes=[Node('smooth',id='a'),Node('slope',id='b',inputs={'dem':'a'})])
    project=Project(tmp_path/'styles',w,{'$dem':dem[0]})
    report=Pipeline(project).run(); report.results['a'].style.ramp='magma'
    assert len(Pipeline(project).run().cache_hits)==2
