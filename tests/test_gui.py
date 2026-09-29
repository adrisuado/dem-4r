from PySide6.QtWidgets import QApplication
from dem_tool.core.models import Project,Workflow,ProcessingNode,Layer
from dem_tool.gui.main_window import MainWindow
from dem_tool.gui.dialogs import NodeDialog


def test_gui_load_render_and_form(tmp_path,dem):
    app=QApplication.instance() or QApplication([])
    p=Project(tmp_path/'gui',Workflow(nodes=[ProcessingNode('slope',id='s')]),{'$dem':dem[0]},[Layer(dem[0],temporary=False)])
    window=MainWindow(p); window.show(); app.processEvents()
    window.select_layer(p.layers[0]); app.processEvents()
    assert window.statistics.layer.path==dem[0]
    assert window.map.bounds
    assert any(hasattr(i,'toPlainText') and 'slope' in i.toPlainText() for i in window.pipeline.scene.items())
    dialog=NodeDialog(p.workflow.nodes[0],p.workflow,p.sources)
    dialog.controls['units'][0].setCurrentText('percent')
    assert dialog.build().parameters['units']=='percent'
    assert window.grab().save(str(tmp_path/'gui.png'))
    window.hide(); window.deleteLater(); app.processEvents()


def test_gui_worker_runs_real_pipeline(tmp_path,dem):
    from PySide6.QtCore import QEventLoop,QTimer
    app=QApplication.instance() or QApplication([])
    p=Project(tmp_path/'worker',Workflow(nodes=[ProcessingNode('slope',id='s')]),{'$dem':dem[0]})
    window=MainWindow(p); window.show(); window.execute()
    loop=QEventLoop(); window.worker.finished.connect(loop.quit); QTimer.singleShot(30000,loop.quit); loop.exec()
    assert not window.worker.isRunning()
    app.processEvents()
    assert window.statuses['s']=='Completed'
    assert len(window.project.layers)>=1 and window.run_button.isEnabled()
    window.hide(); window.deleteLater(); app.processEvents()


def test_histogram_auto_frame_groups_and_detached_graph(tmp_path,dem):
    app=QApplication.instance() or QApplication([])
    layer=Layer(dem[0],temporary=False)
    p=Project(tmp_path/'view',Workflow(nodes=[ProcessingNode('slope',id='s')]),{'$dem':dem[0]},[layer])
    window=MainWindow(p); window.show(); app.processEvents(); window.map.canvas.draw()
    assert window.statistics.layer.path==dem[0]  # no tree selection required
    assert window.statistics.figure.axes[0].patches
    assert window.map.ax.get_position().width>.85
    assert len(window.pipeline.category_buttons)==6
    for category,button in window.pipeline.category_buttons.items():
        assert button.menu().actions()
    panel=window.pipeline; scene=panel.scene
    window.toggle_graph_window(); app.processEvents()
    assert window.graph_window.isVisible() and window.pipeline.scene is scene
    window.pipeline.show_workflow(p.workflow,{'s':'Completed'})
    window.graph_window.close(); app.processEvents()
    assert window.pipeline is panel and window.pipeline.parentWidget() is window.pipeline_holder
    assert window.pipeline.statuses['s']=='Completed'
    layer.visible=False; window.map.draw_layers(p.layers); app.processEvents()
    assert window.statistics.layer is None
    window.hide(); window.deleteLater(); app.processEvents()


def test_reclassification_interval_widgets_and_variable_dialog(tmp_path,dem):
    from dem_tool.gui.dialogs import RulesTable
    from dem_tool.gui.workflow_dialog import WorkflowVariablesDialog
    app=QApplication.instance() or QApplication([])
    rules=RulesTable([[0,5,1,False],[5,10,2,True]])
    assert rules.value()[0][3]=='[a,b)'
    rules.table.cellWidget(0,3).setCurrentIndex(1)
    assert rules.value()[0][3]=='(a,b]'
    workflow=Workflow(nodes=[ProcessingNode('slope',id='s',inputs={'dem':'$terrain'})])
    dialog=WorkflowVariablesDialog(workflow,{'$terrain':dem[0]})
    workflow2,sources,unit=dialog.build()
    assert sources['$terrain']==dem[0] and workflow2.nodes[0].id=='s'
    assert workflow.nodes[0].parameters=={}  # edits are isolated until accepted


def test_vector_extent_picker_creates_reusable_input(tmp_path,dem,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    import geopandas as gpd
    from shapely.geometry import box
    app=QApplication.instance() or QApplication([])
    vector=tmp_path/'extent.gpkg'
    gpd.GeoDataFrame({'id':[1]},geometry=[box(300010,8699400,300200,8699900)],crs=32718).to_file(vector)
    node=ProcessingNode('clip',id='c'); workflow=Workflow(nodes=[node])
    dialog=NodeDialog(node,workflow,{'$dem':dem[0]})
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args:(str(vector),'Vector'))
    dialog.choose_vector('extent')
    result=dialog.build()
    assert result.inputs['extent']=='$extent_c' and dialog.new_sources['$extent_c']==str(vector)
