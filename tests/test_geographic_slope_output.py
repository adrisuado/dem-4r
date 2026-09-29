from pathlib import Path
import json
import numpy as np
import pytest
from pyproj import Geod
from rasterio.transform import from_origin, Affine
from dem_tool.io.raster_io import read_raster, write_raster
from dem_tool.core.models import Layer, Project, Workflow, ProcessingNode
from dem_tool.core.pipeline import Pipeline
from dem_tool.batch.batch_processor import BatchProcessor, BatchItem


def geographic_dem(tmp_path, latitude=0):
    y,x=np.mgrid[:9,:11]
    # Unequal angular X/Y resolution, both longitudinal and meridional gradient.
    profile={'driver':'GTiff','width':11,'height':9,'count':1,'crs':'EPSG:4326',
             'transform':from_origin(-75,latitude+.009/2,.002,.001),'dtype':'float64','nodata':np.nan}
    a=1000+20*x-30*y
    path=write_raster(tmp_path/'geo.tif',a,profile)
    return path,a,profile


@pytest.mark.parametrize('latitude',[0,-12,60,85])
@pytest.mark.parametrize('method',['horn','zevenbergen_thorne'])
def test_geographic_slope_ellipsoidal_distances(tmp_path,run_algorithm,latitude,method):
    path,a,profile=geographic_dem(tmp_path,latitude)
    result=run_algorithm('slope',{'method':method},{'dem':Layer(path)})
    out,p=read_raster(result.path)
    geod=Geod(ellps='WGS84')
    for row in range(1,8):
        lat=profile['transform'].f-(row+.5)*.001
        dx=geod.inv(-75,lat,-74.998,lat)[2]
        dy=geod.inv(-75,lat-.0005,-75,lat+.0005)[2]
        expected=np.degrees(np.arctan(np.hypot(20/dx,30/dy)))
        assert np.allclose(out[row,1:-1],expected,atol=1e-8)
    assert p['crs']==profile['crs'] and p['transform']==profile['transform']
    assert out.shape==a.shape and np.isnan(out[[0,-1],:]).all() and np.isnan(out[:,[0,-1]]).all()
    assert result.metadata['distance_model']=='geodesic_per_row'
    assert result.metadata['ellipsoid']=='WGS 84'


def test_geographic_units_nodata_and_local_edges(tmp_path,run_algorithm):
    path,a,p=geographic_dem(tmp_path,-12)
    a=a.astype(float); a[4,5]=np.nan; a[2,2]=0
    path=write_raster(path,a,p)
    feet=write_raster(tmp_path/'feet.tif',a/.3048,p)
    degrees,_=read_raster(run_algorithm('slope',inputs={'dem':Layer(path)}).path)
    percent,_=read_raster(run_algorithm('slope',{'units':'percent','vertical_unit':'ft'}, {'dem':Layer(feet)}).path)
    assert np.allclose(percent,100*np.tan(np.radians(degrees)),equal_nan=True)
    assert np.isnan(degrees[3:6,4:7]).all() and np.isfinite(degrees[2,2])
    local,_=read_raster(run_algorithm('slope',{'edges':'local'}, {'dem':Layer(path)}).path)
    assert np.isfinite(local[0]).all() and np.isnan(local[3:6,4:7]).all()


def test_geographic_rejects_bad_extent_and_rotation(tmp_path):
    from dem_tool.algorithms.terrain import slope_distances
    _,_,p=geographic_dem(tmp_path)
    with pytest.raises(ValueError,match='latitudes'):
        slope_distances(p|{'transform':from_origin(0,100,.001,.001)})
    with pytest.raises(ValueError,match='rectifique'):
        slope_distances(p|{'transform':p['transform']*Affine.rotation(1)})


def test_output_folder_persistence_cache_and_legacy(tmp_path,dem):
    node=ProcessingNode('slope',id='s')
    p=Project(tmp_path/'project',Workflow(nodes=[node]),{'$dem':dem[0]},output_directory=str(tmp_path/'chosen'))
    p.save(); restored=Project.load(p.root/'project.json')
    assert restored.output_root==p.output_root
    first=Pipeline(restored).run(); assert not first.errors and len(first.exports)==1
    assert Path(first.exports[0]).is_relative_to(p.output_root)
    assert Path(first.log).is_relative_to(p.root/'logs')
    assert Path(first.results['s'].path).is_relative_to(p.root/'temporary')
    restored.output_directory='new_output'  # Relative paths resolve against the project.
    restored.save(); restored=Project.load(p.root/'project.json')
    second=Pipeline(restored).run()
    assert not second.errors and second.cache_hits==['s']
    assert Path(second.exports[0]).is_relative_to(p.root/'new_output')
    assert Path(first.exports[0]).exists()
    data=json.loads((p.root/'project.json').read_text(encoding='utf-8')); data.pop('output_directory')
    (p.root/'project.json').write_text(json.dumps(data),encoding='utf-8')
    assert Project.load(p.root/'project.json').output_root==p.root


def test_output_folder_cannot_be_cleaned_as_temporary(tmp_path,dem):
    p=Project(tmp_path/'project',Workflow(nodes=[ProcessingNode('slope')]),{'$dem':dem[0]},output_directory='temporary/export')
    with pytest.raises(ValueError,match='temporary'):Pipeline(p).run()
    p.output_directory=dem[0]
    with pytest.raises(ValueError,match='archivo'):Pipeline(p).run()


def test_batch_custom_output_isolated_from_projects(tmp_path,dem):
    w=Workflow(nodes=[ProcessingNode('slope',id='s')])
    outputs=tmp_path/'selected'
    report=BatchProcessor(w,tmp_path/'batch',workers=2,output_directory=outputs).run([BatchItem(dem[0]),BatchItem(dem[0])])
    assert all(row['status']=='Completed' for row in report.values()),report
    assert report[0]['output']!=report[1]['output']
    for row in report.values():
        assert Path(row['output']).is_relative_to(outputs)
        assert all(Path(f).is_relative_to(row['output']) for f in row['exports'])
        assert Project.load(Path(row['project'])/'project.json').output_root==Path(row['output'])
