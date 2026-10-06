"""Ejecuta la plantilla sobre un DEM/AOI real y guarda evidencia sin modificar insumos."""
import argparse
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from time import perf_counter
import geopandas as gpd
import numpy as np
from dem_tool.core.models import Project,Layer,atomic_json
from dem_tool.core.pipeline import Pipeline
from dem_tool.core.templates import microbasins_template
from dem_tool.io.raster_io import read_raster


def main():
    """Verifica no solape, áreas, exportación y captura de la plantilla real."""
    parser=argparse.ArgumentParser()
    parser.add_argument('--dem',required=True); parser.add_argument('--mask',required=True)
    parser.add_argument('--crs',required=True); parser.add_argument('--output',required=True)
    args=parser.parse_args(); start=perf_counter()
    root=Path(args.output).resolve()
    workflow=microbasins_template(args.crs,use_aoi=True)
    project=Project(root/'project',workflow,{'$dem':str(Path(args.dem).resolve()),'$mask':str(Path(args.mask).resolve())})
    report=Pipeline(project,on_event=lambda n,s,m:print(n,s,m,flush=True)).run()
    assert not report.errors,report.errors
    assert len(report.exports)==1
    frame=gpd.read_file(report.exports[0],layer='microcuencas')
    mask=gpd.read_file(args.mask).to_crs(frame.crs).union_all()
    assert frame.is_valid.all() and frame.MB_ID.is_unique
    assert np.allclose(frame.AREA_KM2,frame.area/1e6)
    assert (frame.AREA_KM2>=.1).all()
    overlap=float(frame.area.sum()-frame.union_all().area)
    outside=float(frame.difference(mask).area.sum())
    assert abs(overlap)<1 and outside<1,(overlap,outside)
    classes,profile=read_raster(report.results['subcatchments'].path)
    final=report.results['microbasins']
    evidence={'elapsed_seconds':perf_counter()-start,'nodes':len(workflow.nodes),'errors':report.errors,
        'output':report.exports[0],'count':len(frame),'total_area_km2':float(frame.AREA_KM2.sum()),
        'median_area_km2':float(frame.AREA_KM2.median()),'overlap_m2':overlap,'outside_aoi_m2':outside,
        'routing_shape':list(classes.shape),'link_count':report.results['links'].metadata['link_count'],
        'coverage':report.results['subcatchments'].metadata,'final':final.metadata}
    atomic_json(root/'verification.json',evidence)
    from PySide6.QtWidgets import QApplication
    from dem_tool.gui.main_window import MainWindow
    from gui_wait import wait_views
    dem=report.results['dem_metric']; dem.visible=True
    project.layers=[dem,Layer(final.path,name='Microcuencas finales',kind='vector')]
    project.save()
    app=QApplication.instance() or QApplication([])
    window=MainWindow(project);window.resize(1720,1080);window.show();window.statuses=report.statuses
    window.refresh();wait_views(window);window.pipeline.fit()
    window.map.full_extent(project.layers[-1]);wait_views(window)
    window.grab().save(str(root/'microcuencas.png'))
    window.hide();window.deleteLater();app.processEvents()
    print({k:v for k,v in evidence.items() if k not in ('coverage','final')},flush=True)


if __name__=='__main__':main()
