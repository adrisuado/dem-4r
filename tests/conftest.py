import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('NUMBA_NUM_THREADS','2')
import numpy as np
import pytest
from rasterio.transform import from_origin
from dem_tool.io.raster_io import write_raster
from dem_tool.core.models import Layer,Project,Workflow,ProcessingNode
from dem_tool.core.pipeline import Pipeline


@pytest.fixture
def dem(tmp_path):
    y,x=np.mgrid[0:40,0:50]
    a=1000+.2*x*10-.3*y*20
    profile={'driver':'GTiff','width':50,'height':40,'count':1,'crs':'EPSG:32718',
             'transform':from_origin(300000,8700000,10,20),'dtype':'float64','nodata':np.nan}
    path=write_raster(tmp_path/'dem.tif',a,profile)
    return path,a,profile


@pytest.fixture
def run_algorithm(tmp_path,dem):
    def run(name,params=None,inputs=None):
        node=ProcessingNode(name,parameters=params or {},inputs={k:'$'+k for k in inputs} if inputs else {'dem':'$dem'})
        project=Project(tmp_path/(name+'_project'),Workflow(nodes=[node],export_policy='none'),{'$dem':dem[0]})
        sources={'$'+k:v for k,v in inputs.items()} if inputs else {'$dem':Layer(dem[0],temporary=False)}
        report=Pipeline(project).run(sources)
        assert not report.errors,report.errors
        return report.results[node.id]
    return run
