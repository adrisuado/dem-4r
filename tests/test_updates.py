from dataclasses import asdict
from pathlib import Path
import json
import numpy as np
import geopandas as gpd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
from pyproj import Geod
from dem_tool.io.raster_io import read_raster,write_raster,StatisticsCache,OUTPUT_DTYPES
from dem_tool.io.spatial import expand_bounds
from dem_tool.core.models import Workflow,ProcessingNode as Node,Layer,Project
from dem_tool.core.pipeline import Pipeline
from dem_tool.core.workflow_bundle import export_bundle,load_bundle,input_variables
from dem_tool.algorithms.intervals import validate_rules,normalize_interval


@pytest.mark.parametrize('dtype',OUTPUT_DTYPES)
def test_all_output_dtypes(dtype,tmp_path,dem):
    values=np.array([[0,1,np.nan],[2,3,4]],dtype=float)
    path=write_raster(tmp_path/(dtype+'.tif'),values,dem[2],dtype=dtype)
    with rasterio.open(path) as src:
        assert src.dtypes==(dtype,)
        assert src.read(1,masked=True).mask[0,2]
        assert not src.read(1,masked=True).mask[0,0]
    assert np.allclose(read_raster(path)[0],values,equal_nan=True)


def test_uint8_full_range_keeps_valid_zero_and_nodata(tmp_path,dem):
    values=np.arange(257,dtype=float)[None,:]; values[0,-1]=np.nan
    path=write_raster(tmp_path/'full.tif',values,dem[2],dtype='uint8')
    with rasterio.open(path) as src:
        assert src.nodata is None
        data=src.read(1,masked=True)
        assert data.count()==256 and data[0,0]==0 and data[0,255]==255 and data.mask[0,256]


@pytest.mark.parametrize('dtype,value',[('uint8',-1),('int8',128),('int16',32768),('uint16',65536),('uint32',2**32),('int8',1.5)])
def test_integer_overflow_rejected(dtype,value,tmp_path,dem):
    with pytest.raises(ValueError,match='rango'):
        write_raster(tmp_path/'overflow.tif',np.array([[value]],dtype=float),dem[2],dtype=dtype)


@pytest.mark.parametrize('interval,expected',[('[a,b)',[1,1,np.nan]),('(a,b]',[np.nan,1,1]),('[a,b]',[1,1,1]),('(a,b)',[np.nan,1,np.nan])])
def test_explicit_interval_endpoints(interval,expected,run_algorithm,dem,tmp_path):
    path=write_raster(tmp_path/'bounds.tif',np.array([[0,5,10]],dtype=float),dem[2])
    layer=run_algorithm('reclassify',{'rules':[[0,10,1,interval]]},{'dem':Layer(path)})
    assert np.allclose(read_raster(layer.path)[0][0],expected,equal_nan=True)


def test_adjacent_intervals_and_legacy():
    validate_rules([[0,5,1,'(a,b]'],[5,10,2,'(a,b]']])
    with pytest.raises(ValueError,match='superponen'):validate_rules([[0,5,1,'[a,b]'],[5,10,2,'[a,b)']])
    assert normalize_interval(False)=='[a,b)' and normalize_interval(True)=='[a,b]'
    assert normalize_interval('<a,b]')=='(a,b]' and normalize_interval('[a,b>')=='[a,b)'


@pytest.fixture
def geographic_inputs(tmp_path):
    profile={'crs':'EPSG:4326','transform':from_origin(-75.1,-12,0.001,0.001),'dtype':'float64'}
    values=np.arange(10000,dtype=float).reshape(100,100)
    dem=write_raster(tmp_path/'geo.tif',values,profile)
    frame=gpd.GeoDataFrame({'id':[1]},geometry=[box(-75.08,-12.08,-75.04,-12.04)],crs=4326)
    geo=tmp_path/'geo_mask.gpkg'; utm=tmp_path/'utm_mask.gpkg'
    frame.to_file(geo,driver='GPKG'); frame.to_crs(32718).to_file(utm,driver='GPKG')
    return dem,geo,utm


@pytest.mark.parametrize('mask_index',[1,2])
def test_geographic_mask_buffer_and_vector_extent(mask_index,geographic_inputs,run_algorithm):
    dem,*_=geographic_inputs; vector=geographic_inputs[mask_index]
    mask=run_algorithm('clip_mask',{'buffer_m':300},{'dem':Layer(dem),'mask':Layer(str(vector),kind='vector')})
    a,p=read_raster(mask.path)
    assert p['crs'].to_epsg()==4326 and a.shape[0]>40 and a.shape[1]>40
    clipped=run_algorithm('clip',{'expand_m':300},{'dem':Layer(dem),'extent':Layer(str(vector),kind='vector')})
    b,q=read_raster(clipped.path)
    assert q['crs'].to_epsg()==4326 and b.shape[0]>=a.shape[0] and b.shape[1]>=a.shape[1]
    assert np.isfinite(b).all()


def test_extent_crs_and_latitude_conversion(geographic_inputs,run_algorithm):
    dem,geo,utm=geographic_inputs; bounds=gpd.read_file(utm).total_bounds.tolist()
    layer=run_algorithm('clip',{'bounds':bounds,'bounds_crs':'EPSG:32718','expand_m':100},{'dem':Layer(dem)})
    assert read_raster(layer.path)[1]['crs'].to_epsg()==4326
    geod=Geod(ellps='WGS84')
    for lat in (0,70):
        original=(-75.01,lat-.01,-74.99,lat+.01)
        result=expand_bounds(original,4326,1000)
        _,_,distance=geod.inv(original[2],lat,result[2],lat)
        assert 990<distance<1020


def test_statistics_bypass_processing_memory_limit(tmp_path,dem,monkeypatch):
    monkeypatch.setenv('DEM_TOOL_MAX_CELLS','10')
    stats,(counts,_)=StatisticsCache().get(dem[0])
    assert stats['valid_pixels']==2000 and counts.sum()==2000
    a=np.arange(1100000,dtype=float).reshape(1100,1000)
    path=write_raster(tmp_path/'large.tif',a,dem[2])
    stats,(counts,_)=StatisticsCache().get(path)
    assert 'aproximada' in stats['statistics_mode'] and stats['sample_pixels']<=1_000_000
    assert counts.sum()==stats['valid_sample_pixels']


def test_bundle_export_bindings_and_parameter_reuse(tmp_path,dem):
    workflow=Workflow(nodes=[Node('slope',id='s',inputs={'dem':'$terrain'},parameters={'units':'percent'})],prefix='P_',suffix='_v2')
    path=tmp_path/'complete.demflow.json'; export_bundle(path,workflow,{'$terrain':dem[0]},'ft')
    data=json.loads(path.read_text()); assert data['variables']['$terrain']['file_hint']=='dem.tif'
    assert dem[0] not in path.read_text()
    restored,variables,unit=load_bundle(path); assert asdict(restored)==asdict(workflow) and unit=='ft'
    assert variables['$terrain']['kind']=='raster' and Workflow.load(path).prefix=='P_'
    second=write_raster(tmp_path/'replacement.tif',dem[1]+5,dem[2])
    result=Pipeline(Project(tmp_path/'reused',restored,{'$terrain':second},vertical_unit='m')).run()
    assert not result.errors and 's' in result.results
