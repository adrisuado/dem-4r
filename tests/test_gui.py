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
