from pathlib import Path
import threading
import numpy as np
import geopandas as gpd
import pytest
from shapely.geometry import box, MultiPolygon
from dem_tool.algorithms.microbasins import drainage_graph, label_stream_links, assign_local_catchments
from dem_tool.algorithms import load_algorithms
from dem_tool.algorithms.registry import Context, Cancelled
from dem_tool.core.models import Project, Layer
from dem_tool.core.pipeline import Pipeline
from dem_tool.core.templates import microbasins_template
from dem_tool.core.workflow_bundle import export_bundle, load_bundle
from dem_tool.io.raster_io import read_raster, write_raster


def test_adjacent_parallel_channels_are_separate_links():
    direction=np.array([[4.,4.],[4.,4.],[0.,0.]])
    receiver,order=drainage_graph(direction)
    labels,count=label_stream_links(receiver,order,np.ones(6,dtype=bool))
    labels=labels.reshape(3,2)
    assert count==2
    assert len(np.unique(labels[:,0]))==len(np.unique(labels[:,1]))==1
    assert labels[0,0]!=labels[0,1]


def test_confluence_and_first_reachable_link_not_nested_basins():
    d=np.full((5,5),np.nan)
    d[0,0]=2; d[0,4]=8  # hillslope to upstream branches
    d[1,1]=2; d[1,3]=8  # confluence at (2,2)
    d[2,2]=4; d[3,2]=4; d[4,2]=0
    stream=np.zeros_like(d,dtype=bool); stream[1,1]=stream[1,3]=True; stream[2:,2]=True
    receiver,order=drainage_graph(d)
    seeds,count=label_stream_links(receiver,order,stream.ravel())
    out=assign_local_catchments(receiver,order,seeds).reshape(d.shape)
    assert count==3
    assert out[0,0]==out[1,1] and out[0,4]==out[1,3]
    assert out[2,2]==out[3,2]==out[4,2]
    assert len({out[1,1],out[1,3],out[2,2]})==3
    assert np.count_nonzero(out)==np.isfinite(d).sum()


@pytest.mark.parametrize('direction',[np.array([[1.,16.]]),np.array([[2.,np.nan],[64.,16.]])])
def test_d8_cycles_are_rejected(direction):
    with pytest.raises(ValueError,match='ciclos'):drainage_graph(direction)


def test_no_wrap_at_edges_or_routing_across_nodata():
    d=np.array([[16.,np.nan,1.],[4.,64.,4.]])
    receiver,order=drainage_graph(d)
    assert np.all(receiver==-1)
    assert len(order)==5
    assert not assign_local_catchments(receiver,order,np.zeros(6,dtype=np.int32)).any()
    with pytest.raises(ValueError,match='Código'):drainage_graph(np.array([[3.]]))


@pytest.mark.parametrize('use_aoi',[False,True])
def test_complete_template_area_export_and_cache(tmp_path,dem,use_aoi):
    y,x=np.mgrid[0:40,0:50]
    source=write_raster(tmp_path/'valley.tif',1000+(x-25)**2*.2+(40-y)*3.,dem[2])
    sources={'$dem':source}
    aoi=gpd.GeoDataFrame(geometry=[box(300050,8699300,300450,8699900)],crs=32718)
    if use_aoi:
        path=tmp_path/'aoi.gpkg'; aoi.to_crs(4326).to_file(path); sources['$mask']=str(path)
    w=microbasins_template('EPSG:32718',10,.001,0,use_aoi,100)
    p=Project(tmp_path/'p',w,sources)
    report=Pipeline(p).run()
    assert not report.errors,report.errors
    assert len(report.results)==(11 if use_aoi else 10)
    assert len(report.exports)==1 and Path(report.exports[0]).suffix=='.gpkg'
    a,profile=read_raster(report.results['subcatchments'].path)
    vector=gpd.read_file(report.exports[0],layer='microcuencas')
    assert set(vector.columns)=={'MB_ID','LINK','AREA_KM2','geometry'}
    assert vector.MB_ID.is_unique and vector.LINK.min()>0
    assert vector.is_valid.all()
    assert np.allclose(vector.AREA_KM2,vector.area/1e6)
    assert vector.area.sum()==pytest.approx(vector.union_all().area)
    if use_aoi:assert vector.difference(aoi.union_all()).area.sum()<1e-5
    else:assert vector.AREA_KM2.sum()==pytest.approx(np.isfinite(a).sum()*abs(profile['transform'].a*profile['transform'].e)/1e6)
    second=Pipeline(p).run(); assert not second.errors
    assert len(second.cache_hits)==len(w.nodes)
    bundle=tmp_path/'recipe.demflow.json'; export_bundle(bundle,w,sources)
    loaded,variables,unit=load_bundle(bundle)
    assert loaded==w and set(variables)==({'$dem','$mask'} if use_aoi else {'$dem'})


def test_vector_filter_applies_after_explode_and_preserves_links(tmp_path):
    p=tmp_path/'parts.gpkg'
    gpd.GeoDataFrame({'value':[7]},geometry=[MultiPolygon([box(0,0,1000,1000),box(2000,0,2200,200)])],crs=32718).to_file(p)
    outdir=tmp_path/'out'; outdir.mkdir()
    ctx=Context(outdir,threading.Event())
    result=load_algorithms()['finalize_microbasins'].run({'vector':Layer(str(p),kind='vector')},{'min_area_km2':.1},ctx)
    frame=gpd.read_file(result.path)
    assert len(frame)==1 and frame.LINK.iloc[0]==7 and frame.MB_ID.iloc[0]=='MB-00001'
    assert frame.AREA_KM2.iloc[0]==1
    assert result.metadata['discarded_parts']==1 and result.metadata['discarded_area_km2']==pytest.approx(.04)


@pytest.mark.parametrize('kwargs',[{'crs':'EPSG:4326'},{'resolution':0},{'threshold_km2':-1},{'min_area_km2':float('nan')},{'margin_m':-5}])
def test_template_rejects_invalid_metric_configuration(kwargs):
    with pytest.raises(ValueError):microbasins_template(**kwargs)


def test_empty_streams_and_mismatched_direction_are_actionable(tmp_path,dem):
    from dem_tool.algorithms.hydrology import DIRMAP
    directory=tmp_path/'out'; directory.mkdir();ctx=Context(directory,threading.Event())
    da=write_raster(tmp_path/'direction.tif',np.full(dem[1].shape,4.),dem[2])
    sa=write_raster(tmp_path/'streams.tif',np.zeros(dem[1].shape),dem[2])
    direction=Layer(da,metadata={'quantity':'d8_direction','dirmap':list(DIRMAP)})
    streams=Layer(sa,metadata={'quantity':'stream_mask','direction_path':da})
    algorithm=load_algorithms()['stream_links']
    with pytest.raises(ValueError,match='No hay cauces'):algorithm.run({'direction':direction,'streams':streams},{},ctx)
    streams.metadata['direction_path']='other.tif'
    with pytest.raises(ValueError,match='misma rama'):algorithm.run({'direction':direction,'streams':streams},{},ctx)


def test_microbasins_dialog_and_menu_expose_template(tmp_path,dem):
    from PySide6.QtWidgets import QApplication
    from dem_tool.gui.microbasins_dialog import MicrobasinsDialog,suggest_metric_crs
    from dem_tool.gui.pipeline_panel import PipelinePanel
    app=QApplication.instance() or QApplication([])
    dialog=MicrobasinsDialog({'$dem':dem[0]})
    workflow,sources=dialog.build()
    assert len(workflow.nodes)==10 and sources=={'$dem':dem[0]}
    assert workflow.nodes[0].parameters['crs']=='EPSG:32718'
    assert not dialog.mask.isEnabled() and not dialog.margin.isEnabled()
    assert suggest_metric_crs(dem[0])=='EPSG:32718'
    panel=PipelinePanel(); assert panel.template.findText('Microcuencas por tramos D8')>=0
    for node in workflow.nodes:assert node.algorithm in load_algorithms()
    dialog.deleteLater();panel.deleteLater();app.processEvents()
