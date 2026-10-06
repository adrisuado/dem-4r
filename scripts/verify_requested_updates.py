"""Integration QA with the user's real inputs, never modifying the source project."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import json
import threading
from dataclasses import asdict
import rasterio
from dem_tool.algorithms import load_algorithms
from dem_tool.algorithms.registry import Context
from dem_tool.core.models import Project,Workflow,Layer,ProcessingNode,atomic_json
from dem_tool.core.workflow_bundle import export_bundle
from dem_tool.io.raster_io import StatisticsCache

root=Path('test-output/updates_20260929').resolve(); root.mkdir(parents=True,exist_ok=True)
source=Project.load('workspace/Proyecto_20260929_020610/project.json')
inputs={'dem':Layer(source.sources['$dem']),'mask':Layer(source.sources['$mask'],kind='vector')}
registry=load_algorithms(); report={}
for algorithm,params,ports in [('clip_mask',{'buffer_m':30},inputs),
                               ('clip',{'expand_m':200},{'dem':inputs['dem'],'extent':inputs['mask']})]:
    directory=root/algorithm; directory.mkdir(exist_ok=True)
    result=registry[algorithm].run(ports,params,Context(directory,threading.Event()))
    with rasterio.open(result.path) as ds:
        report[algorithm]={'path':result.path,'crs':str(ds.crs),'shape':list(ds.shape),'bounds':list(ds.bounds),'valid_pixels':int(ds.read_masks(1).astype(bool).sum())}
    if algorithm=='clip_mask':clipped=result
stats,hist=StatisticsCache().get(inputs['dem'].path)
assert 'aproximada' in stats['statistics_mode'] and hist[0].sum()>0
report['original_dem_statistics']=stats
project=Project(root/'preview',Workflow.from_dict(asdict(source.workflow)),dict(source.sources),
                [Layer(inputs['dem'].path,name='ANADEM original · histograma muestreado',temporary=False)])
export_bundle(root/'flujo_reutilizable.demflow.json',project.workflow,project.sources)
from PySide6.QtWidgets import QApplication
from dem_tool.gui.main_window import MainWindow
from dem_tool.gui.dialogs import NodeDialog
from dem_tool.gui.workflow_dialog import WorkflowVariablesDialog
app=QApplication([]); window=MainWindow(project); window.resize(1600,1120); window.show(); app.processEvents(); window.pipeline.fit(); app.processEvents()
from gui_wait import wait_views
wait_views(window)
window.grab().save(str(root/'01_mapa_histograma.png'))
project.layers[0].visible=False; clipped.name='Yanacancha · máscara + 30 m'; project.layers.append(clipped); window.refresh(); app.processEvents()
window.toggle_graph_window(); app.processEvents(); window.pipeline.fit(); app.processEvents()
from gui_wait import wait_views
wait_views(window)
window.graph_window.grab().save(str(root/'02_flujo_independiente.png'))
window.graph_window.close(); app.processEvents()
node=next(n for n in project.workflow.nodes if n.algorithm=='reclassify')
dialog=NodeDialog(node,project.workflow,project.sources,window); dialog.show(); app.processEvents(); dialog.grab().save(str(root/'03_intervalos.png')); dialog.hide()
variables=WorkflowVariablesDialog(project.workflow,project.sources,parent=window); variables.show(); app.processEvents(); variables.grab().save(str(root/'04_variables.png')); variables.hide()
window.hide(); project.save(); atomic_json(root/'report.json',report)
print(json.dumps(report,ensure_ascii=False,indent=2))
