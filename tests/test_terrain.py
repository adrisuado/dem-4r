import numpy as np
import pytest
from dem_tool.io.raster_io import read_raster,write_raster
from dem_tool.core.models import Layer,Project,Workflow,ProcessingNode
from dem_tool.core.pipeline import Pipeline


def test_horn_rectangular_plane(run_algorithm):
    layer=run_algorithm('slope')
    a,_=read_raster(layer.path)
    assert np.allclose(a[1:-1,1:-1],np.degrees(np.arctan(np.hypot(.2,.3))),atol=1e-9)
    assert np.isnan(a[0]).all()


def test_aspect_and_curvature_plane(run_algorithm):
    a,_=read_raster(run_algorithm('aspect').path)
    assert np.allclose(a[1:-1,1:-1],np.degrees(np.arctan2(-.2,-.3))%360)
    for kind in ('general','profile','plan','tangential'):
        a,_=read_raster(run_algorithm('curvature',{'kind':kind}).path)
        assert np.nanmax(abs(a))<1e-10


def test_vertical_conversion(run_algorithm,dem,tmp_path):
    path=write_raster(tmp_path/'feet.tif',dem[1]/.3048,dem[2])
    result=run_algorithm('slope',{'vertical_unit':'ft'}, {'dem':Layer(path)})
    a,_=read_raster(result.path)
    assert np.allclose(a[1:-1,1:-1],np.degrees(np.arctan(np.hypot(.2,.3))))


def test_other_metric_derivatives_still_require_projected_crs(tmp_path,dem):
    profile=dem[2]|{'crs':'EPSG:4326'}
    path=write_raster(tmp_path/'geo.tif',dem[1],profile)
    node=ProcessingNode('curvature'); project=Project(tmp_path/'p',Workflow(nodes=[node]),{'$dem':path})
    r=Pipeline(project).run()
    assert 'reproyecte' in r.errors[node.id]


def test_neighbors_constant_surface(run_algorithm,dem,tmp_path):
    path=write_raster(tmp_path/'flat.tif',np.full_like(dem[1],100),dem[2])
    for algorithm in ('tpi','tri','roughness','local_relief','vrm'):
        a,_=read_raster(run_algorithm(algorithm,inputs={'dem':Layer(path)}).path)
        assert np.nanmax(abs(a))<1e-8


def test_tpi_and_tri_center_peak(run_algorithm,dem,tmp_path):
    a=np.zeros_like(dem[1]); a[20,25]=10
    path=write_raster(tmp_path/'peak.tif',a,dem[2])
    tpi,_=read_raster(run_algorithm('tpi',inputs={'dem':Layer(path)}).path)
    tri,_=read_raster(run_algorithm('tri',inputs={'dem':Layer(path)}).path)
    assert tpi[20,25]==10
    assert tri[20,25]==pytest.approx(np.sqrt(8*100))


def test_gaps_boundary_and_large(run_algorithm,dem,tmp_path):
    a=dem[1].copy(); a[0:4,:3]=np.nan; a[15,15]=np.nan; a[25:30,25:30]=np.nan
    path=write_raster(tmp_path/'gaps.tif',a,dem[2])
    layer=run_algorithm('fill_gaps',{'max_gap':5},{'dem':Layer(path)})
    out,_=read_raster(layer.path)
    assert np.isfinite(out[15,15]); assert np.isnan(out[0:4,:3]).all(); assert np.isnan(out[25:30,25:30]).all()


def test_smoothing_and_hillshade(run_algorithm,dem,tmp_path):
    for method in ('median','mean','gaussian'):
        a,_=read_raster(run_algorithm('smooth',{'method':method}).path)
        assert np.allclose(a[5:-5,5:-5],dem[1][5:-5,5:-5])
    a,_=read_raster(run_algorithm('hillshade').path)
    assert np.nanmin(a)>=0 and np.nanmax(a)<=255


def test_nodata_not_elevation_zero(run_algorithm,dem,tmp_path):
    a=dem[1].copy(); a[20,20]=np.nan; a[10,10]=0
    path=write_raster(tmp_path/'masked.tif',a,dem[2])
    out,_=read_raster(run_algorithm('slope',inputs={'dem':Layer(path)}).path)
    assert np.isnan(out[19:22,19:22]).all()
    assert np.isfinite(out[10,10])


def test_curvature_bundle_bands_and_extract(run_algorithm):
    import rasterio
    layer=run_algorithm('curvatures',{'packaging':'both'})
    with rasterio.open(layer.path) as src:
        assert src.count==3 and src.descriptions==('general','profile','plan')
        assert np.nanmax(abs(src.read()[:,2:-2,2:-2]))<1e-10
    assert len(layer.metadata['artifacts'])==3
    out=run_algorithm('select_band',{'band':2},{'dem':layer})
    assert read_raster(out.path)[0].ndim==2
