"""Generate explicit test fixtures and reproducible acceptance evidence (not real terrain)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('NUMBA_NUM_THREADS','2')
from pathlib import Path
import json
import numpy as np
from rasterio.transform import from_origin
from dem_tool.io.raster_io import write_raster,read_raster
from dem_tool.core.models import Project,Layer,atomic_json
from dem_tool.core.templates import relief_template,hydrology_template
from dem_tool.core.pipeline import Pipeline
from dem_tool.batch.batch_processor import BatchProcessor,BatchItem


def main():
    root=Path('test-output/acceptance').resolve(); root.mkdir(parents=True,exist_ok=True)
    y,x=np.mgrid[0:100,0:120]
    z=1800+(x-60)**2*.1+(100-y)*2+60*np.exp(-((x-32)**2+(y-40)**2)/180)
    z[40,60]-=15
    profile={'driver':'GTiff','width':120,'height':100,'count':1,'crs':'EPSG:32718',
             'transform':from_origin(300000,8700000,20,20),'dtype':'float64'}
    source=write_raster(root/'TEST_FIXTURE_DEM.tif',z,profile,{'description':'Synthetic fixture for QA only; not real terrain'})
    results={}
    projects=[]
    for name,workflow in [('relief',relief_template('EPSG:32718',[300100,8698100,302300,8699900])),('hydrology',hydrology_template())]:
        if name=='hydrology':workflow.nodes[-1].parameters={'threshold':.025,'unit':'km2','vector':True,'strahler':True}
        project=Project(root/name,workflow,{'$dem':source}); first=Pipeline(project).run(); second=Pipeline(project).run()
        assert not first.errors and not second.errors,(first.errors,second.errors)
        assert len(second.cache_hits)==len(workflow.nodes)
        project.layers=[Layer(source,name='DEM sintético · SOLO QA',temporary=False),*first.results.values()]
        for i,l in enumerate(project.layers):l.visible=(i in (0,3))
        project.save(); projects.append(project)
        results[name]={'nodes':len(first.results),'exports':len(first.exports),'cache_hits_second_run':len(second.cache_hits),'errors':first.errors,'log':first.log}
    batch=BatchProcessor(projects[0].workflow,root/'batch',workers=2).run([BatchItem(source),BatchItem(source)])
    assert all(v['status']=='Completed' for v in batch.values())
    for outcome in batch.values():
        loaded=Project.load(Path(outcome['output'])/'project.json')
        single={layer.name:layer for layer in projects[0].layers[1:]}
        for layer in loaded.layers:
            if layer.kind=='raster':
                a,p=read_raster(layer.path); b,q=read_raster(single[layer.name].path)
                assert p['crs']==q['crs'] and p['transform']==q['transform']
                assert np.allclose(a,b,equal_nan=True),layer.name
    results['batch_matches_individual']=True
    results['batch']=batch
    from PySide6.QtWidgets import QApplication
    from dem_tool.gui.main_window import MainWindow
    app=QApplication.instance() or QApplication([])
    window=MainWindow(projects[0]); window.resize(1560,1000); window.show(); app.processEvents()
    window.select_layer(projects[0].layers[3]); window.pipeline.show_workflow(projects[0].workflow,{n.id:'Completed' for n in projects[0].workflow.nodes}); window.pipeline.fit(); app.processEvents()
    from gui_wait import wait_views
    wait_views(window)
    window.grab().save(str(root/'gui_relief.png'))
    window.hide(); window.deleteLater(); app.processEvents()
    atomic_json(root/'acceptance_report.json',results)
    print(json.dumps(results,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
