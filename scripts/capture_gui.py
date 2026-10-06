"""Render an existing QA project without executing its processing workflow."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from PySide6.QtWidgets import QApplication
from dem_tool.core.models import Project
from dem_tool.gui.main_window import MainWindow

root=Path('test-output/acceptance').resolve()
app=QApplication([])
project=Project.load(root/'relief'/'project.json')
window=MainWindow(project); window.resize(1560,1100); window.show(); app.processEvents()
window.select_layer(project.layers[3]); window.pipeline.show_workflow(project.workflow,{n.id:'Completed' for n in project.workflow.nodes}); window.pipeline.fit(); app.processEvents()
from gui_wait import wait_views
wait_views(window)
window.grab().save(str(root/'gui_relief.png'))
window.hide()
