from pathlib import Path
import numpy as np
import geopandas as gpd
from shapely.geometry import Point
from dem_tool.core.models import Project,Workflow,ProcessingNode as Node
from dem_tool.core.pipeline import Pipeline
from dem_tool.core.templates import hydrology_template
from dem_tool.io.raster_io import read_raster,write_raster


def test_hydrology_acceptance_units_strahler(tmp_path,dem):
    y,x=np.mgrid[0:40,0:50]
    z=1000+(x-25)**2*.2+(40-y)*3.; z[20,25]-=15
    path=write_raster(tmp_path/'valley.tif',z,dem[2])
    w=hydrology_template(); w.nodes[-1].parameters={'threshold':5,'unit':'cells','vector':True,'strahler':True}
    p=Project(tmp_path/'hydro',w,{'$dem':path}); r=Pipeline(p).run()
    assert not r.errors,r.errors
    assert len(r.results)==4
    fill=r.results['fill']; assert fill.metadata['filled_volume_m3']>0
    acc,_=read_raster(r.results['accumulation'].path); assert np.nanmax(acc)>1000
    streams,_=read_raster(r.results['streams'].path); assert np.count_nonzero(streams==1)>0
    artifacts=r.results['streams'].metadata['artifacts']; assert any(x.endswith('.gpkg') for x in artifacts)
    assert all(Path(x).exists() for x in artifacts)
    w.nodes[2].parameters={'units':'cells'}; changed=Pipeline(p).run(); assert not changed.errors
    cells,_=read_raster(changed.results['accumulation'].path)
    assert np.allclose(acc,cells*200,equal_nan=True)
    assert np.array_equal(streams,read_raster(changed.results['streams'].path)[0],equal_nan=True)


def test_watershed_snap_and_morphometry(tmp_path,dem):
    y,x=np.mgrid[0:40,0:50]; z=1000+(x-25)**2*.2+(40-y)*3
    path=write_raster(tmp_path/'valley.tif',z,dem[2]); t=dem[2]['transform']; xx,yy=t*(25.5,37.5)
    w=hydrology_template(); w.nodes[-1].parameters={'threshold':5,'unit':'cells','vector':False,'strahler':False}
    w.nodes.extend([
        Node('snap_pour_point',id='snap',inputs={'accumulation':'accumulation'},parameters={'x':xx,'y':yy,'threshold':5,'unit':'cells'}),
        Node('watershed',id='basin',inputs={'direction':'direction','point':'snap'}),
        Node('strahler',id='order',inputs={'direction':'direction','streams':'streams'}),
        Node('morphometry',id='metrics',inputs={'dem':'$dem','basin':'basin','direction':'direction','streams':'streams','order':'order'})])
    r=Pipeline(Project(tmp_path/'watershed',w,{'$dem':path})).run()
    assert not r.errors,r.errors
    a,_=read_raster(r.results['basin'].path)
    accumulation,_=read_raster(r.results['accumulation'].path)
    # D8 may retain parallel paths near the valley floor. Verify the delineation
    # against the contributing cell count at the exact snapped cell, not a guessed area.
    assert np.count_nonzero(a==1)==accumulation[37,25]/200
    assert np.count_nonzero(a==1)>20
    snapped=gpd.read_file(r.results['snap'].path).geometry.iloc[0]
    assert abs(snapped.x-xx)<1e-8 and abs(snapped.y-yy)<1e-8
    metrics=r.results['metrics'].metadata['metrics']; assert metrics['area_m2']==np.count_nonzero(a==1)*200
    assert 0<=metrics['hypsometric_integral']<=1
    assert metrics['main_channel_length_m']>0
    assert all(Path(p).exists() for p in r.results['metrics'].metadata['artifacts'])


def test_shreve_and_strahler_confluence(run_algorithm,dem,tmp_path):
    from dem_tool.core.models import Layer
    from dem_tool.algorithms.hydrology import DIRMAP
    a=np.zeros_like(dem[1]); stream=np.zeros_like(a)
    # Two first-order tributaries converge at row 12, column 20.
    for r,c,code in [(10,18,2),(11,19,2),(10,22,8),(11,21,8),(12,20,4),(13,20,4),(14,20,4)]:
        a[r,c]=code; stream[r,c]=1
    direction=Layer(write_raster(tmp_path/'dir.tif',a,dem[2]),metadata={'quantity':'d8_direction','dirmap':list(DIRMAP)})
    network=Layer(write_raster(tmp_path/'stream.tif',stream,dem[2]))
    for algorithm in ('shreve','strahler'):
        output=run_algorithm(algorithm,inputs={'direction':direction,'streams':network})
        values,_=read_raster(output.path)
        assert values[10,18]==1 and values[10,22]==1 and values[12,20]==2 and values[14,20]==2
