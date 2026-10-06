"""Validate geographic slope and a custom output folder against a real DEM clip."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import argparse
from pathlib import Path
import numpy as np
from dem_tool.core.models import Project, Workflow, ProcessingNode, Layer, atomic_json
from dem_tool.core.pipeline import Pipeline
from dem_tool.io.raster_io import read_raster


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',default='test-output/updates_20260929/clip_mask/result.tif')
    parser.add_argument('--output',default='test-output/geographic_slope_20260929')
    args=parser.parse_args()
    root=Path(args.output).resolve(); source=Path(args.input).resolve()
    data,profile=read_raster(source)
    assert profile['crs'].is_geographic
    nodes=[
        ProcessingNode('slope',id='slope',name='Pendiente_geografica',parameters={'units':'degrees'}),
        ProcessingNode('reclassify',id='classes',inputs={'dem':'slope'},output_dtype='uint8',
                       parameters={'rules':[[0,5,1,'[a,b)'],[5,15,2,'[a,b)'],[15,30,3,'[a,b)'],[30,90,4,'[a,b]']]}),
        ProcessingNode('polygonize',id='polygons',inputs={'dem':'classes'}),
        ProcessingNode('dissolve',id='dissolved',inputs={'vector':'polygons'})]
    project=Project(root/'project',Workflow(nodes=nodes,export_policy='detailed'),{'$dem':str(source)},
                    output_directory=str(root/'salidas_elegidas'))
    report=Pipeline(project,on_event=lambda n,s,m:print(n,s,m,flush=True)).run()
    assert not report.errors,report.errors
    assert len(report.exports)==4
    assert all(Path(f).is_relative_to(project.output_root) for f in report.exports)
    slope=report.results['slope']; out,p=read_raster(slope.path)
    assert p['crs']==profile['crs'] and p['transform']==profile['transform'] and out.shape==data.shape
    assert np.isfinite(out).sum()>0 and np.nanmin(out)>=0 and np.nanmax(out)<90
    project.layers=[Layer(str(source),name='Yanacancha · DEM geográfico',temporary=False,visible=False),slope]
    project.save()
    from PySide6.QtWidgets import QApplication
    from dem_tool.gui.main_window import MainWindow
    app=QApplication.instance() or QApplication([])
    window=MainWindow(project); window.resize(1600,1060); window.show(); app.processEvents()
    window.statuses=report.statuses; window.refresh(); window.pipeline.fit(); app.processEvents()
    from gui_wait import wait_views
    wait_views(window)
    window.grab().save(str(root/'pendiente_geografica_salida.png')); window.hide()
    result={'input':str(source),'crs':str(p['crs']),'shape':list(out.shape),
            'valid_pixels':int(np.isfinite(out).sum()),'min_degrees':float(np.nanmin(out)),
            'max_degrees':float(np.nanmax(out)),'mean_degrees':float(np.nanmean(out)),
            'distance_model':slope.metadata['distance_model'],'ellipsoid':slope.metadata['ellipsoid'],
            'statuses':report.statuses,'exports':report.exports,'errors':report.errors}
    atomic_json(root/'verification.json',result)
    print(result)


if __name__=='__main__':main()
