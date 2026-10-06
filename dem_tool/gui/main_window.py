from __future__ import annotations
from dataclasses import asdict,replace
from datetime import datetime
from pathlib import Path
import json
import shutil
import threading
import uuid

from PySide6.QtCore import Qt,QThread,Signal,QUrl
from PySide6.QtGui import QAction,QDesktopServices,QFontDatabase,QFont
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QSplitter,QTabWidget,QComboBox,QFileDialog,QMessageBox,QInputDialog,QTextEdit,
    QProgressBar,QTableWidget,QTableWidgetItem,QSpinBox,QDialog,QToolBar,QLineEdit)
from dem_tool.core.models import Project,Workflow,ProcessingNode,Layer
from dem_tool.core.pipeline import Pipeline,export_layer
from dem_tool.core.templates import relief_template,hydrology_template
from dem_tool.algorithms import load_algorithms
from dem_tool.batch.batch_processor import BatchProcessor,BatchItem,import_csv,validate_batch
from .map_view import MapView
from .statistics_panel import StatisticsPanel
from .layer_panel import LayerPanel
from .pipeline_panel import PipelinePanel,WorkflowWindow
from .dialogs import NodeDialog,StyleDialog
from .workflow_dialog import WorkflowVariablesDialog
from .microbasins_dialog import MicrobasinsDialog
from dem_tool.core.workflow_bundle import export_bundle,load_bundle


STYLE='''
QMainWindow, QWidget { background:#111c2d; color:#dae6ef; font-family:"DejaVu Sans"; font-size:12px; }
QMenuBar,QMenu,QToolBar,QTabBar::tab { background:#17263a; }
QMenu::item:selected,QTabBar::tab:selected { background:#254356; }
QPushButton,QToolButton { background:#263c51; border:1px solid #385469; border-radius:5px; padding:7px 10px; }
QPushButton:hover { background:#34566a; }
QPushButton:disabled { color:#748394; background:#192637; }
QPushButton#run { background:#147d70; border:1px solid #4ed5bc; font-weight:600; }
QLabel#brand { font-size:24px; font-weight:700; color:#e1f6f4; }
QLabel#section { font-size:13px; font-weight:600; color:#6bdbc6; padding:5px; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QTextEdit,QTextBrowser,QTableWidget,QTreeWidget {
 background:#17263a; border:1px solid #30445a; border-radius:3px; padding:4px; selection-background-color:#256d71; }
QHeaderView::section { background:#203249; color:#acd2dc; padding:7px; border:0; }
QSplitter::handle { background:#293d52; }
QProgressBar { border:1px solid #30445a; border-radius:3px; text-align:center; }
QProgressBar::chunk { background:#229f8a; }
QToolTip { background:#203249; color:#e2f1f6; border:1px solid #5caeaf; }
'''


class Worker(QThread):
    event=Signal(int,str,str,str)
    completed=Signal(object)
    failed=Signal(str)
    def __init__(self,project,items=None,workers=1):
        super().__init__(); self.project=project; self.items=items; self.workers=workers; self.cancel=threading.Event()

    def run(self):
        try:
            if self.items is None:
                report=Pipeline(self.project,self.cancel,lambda n,s,m:self.event.emit(-1,n,s,m)).run()
            else:
                root=self.project.root/'batch'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                output=self.project.output_root/'batch'/root.name if self.project.output_directory else None
                report=BatchProcessor(self.project.workflow,root,self.workers,self.cancel,
                    self.event.emit,self.project.vertical_unit,sources=self.project.sources,output_directory=output).run(self.items)
            self.completed.emit(report)
        except Exception as exc:self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self,project=None):
        super().__init__()
        import matplotlib
        from PySide6.QtWidgets import QApplication
        font_dir=Path(matplotlib.get_data_path())/'fonts'/'ttf'
        for file in ('DejaVuSans.ttf','DejaVuSans-Bold.ttf'):
            QFontDatabase.addApplicationFont(str(font_dir/file))
        QApplication.instance().setFont(QFont('DejaVu Sans',9))
        self.project=project or Project(Path.cwd()/'workspace'/('Proyecto_'+datetime.now().strftime('%Y%m%d_%H%M%S')))
        self.registry=load_algorithms(); self.selected_layer=None; self.worker=None; self.statuses={}; self.batch_items=[]; self.batch_states={}
        self.removed_layers=[]; self._view_project=self.project
        self.setWindowTitle('DEM Workflows · Procesamiento geomorfométrico'); self.resize(1560,1000); self.setMinimumSize(1080,760); self.setStyleSheet(STYLE)
        central=QWidget(); outer=QVBoxLayout(central); outer.setContentsMargins(14,10,14,8); self.setCentralWidget(central)
        header=QHBoxLayout(); brand=QLabel('DEM / WORKFLOWS'); brand.setObjectName('brand'); header.addWidget(brand); header.addStretch()
        self.project_label=QLabel(); header.addWidget(self.project_label); outer.addLayout(header)
        sub=QLabel('RELIEVE · HIDROLOGÍA · FLUJOS REPRODUCIBLES'); sub.setObjectName('section'); outer.addWidget(sub)
        tools=QHBoxLayout(); outer.addLayout(tools)
        for text,callback in [('+ DEM',self.add_dem),('+ Vector / máscara',self.add_vector),('Simbología',self.symbology),('Exportar capa',self.export_selected),('Extensión completa',lambda:self.map.full_extent()),('Zoom a capa',lambda:self.map.full_extent(self.selected_layer))]:
            button=QPushButton(text); button.clicked.connect(callback); tools.addWidget(button)
        tools.addStretch(); tools.addWidget(QLabel('Unidad Z del DEM:')); self.z_unit=QComboBox(); self.z_unit.addItems(['m','ft','us-ft']); self.z_unit.setCurrentText(self.project.vertical_unit); tools.addWidget(self.z_unit)
        vertical=QSplitter(Qt.Orientation.Vertical); outer.addWidget(vertical,1)
        self.mode=QTabWidget(); vertical.addWidget(self.mode)
        self.individual=QSplitter(Qt.Orientation.Horizontal); self.mode.addTab(self.individual,'Individual / mapa')
        layer_holder=QWidget(); layer_layout=QVBoxLayout(layer_holder); layer_layout.setContentsMargins(0,0,0,0)
        self.layers=LayerPanel(); self.layers.setMinimumWidth(195); layer_layout.addWidget(self.layers)
        hint=QLabel('Ctrl / Mayús: selección múltiple'); layer_layout.addWidget(hint)
        layer_buttons=QHBoxLayout(); layer_layout.addLayout(layer_buttons)
        self.remove_layers_button=QPushButton('Quitar (0)'); self.remove_layers_button.setEnabled(False)
        self.remove_layers_button.setToolTip('Supr: quita las capas del entorno. Conserva archivos y entradas del flujo.')
        self.undo_layers_button=QPushButton('Deshacer'); self.undo_layers_button.setEnabled(False)
        self.undo_layers_button.setToolTip('Restaura el último grupo de capas retiradas. Ctrl+Z dentro del árbol de capas.')
        layer_buttons.addWidget(self.remove_layers_button); layer_buttons.addWidget(self.undo_layers_button)
        self.individual.addWidget(layer_holder)
        self.map=MapView(); self.individual.addWidget(self.map)
        self.statistics=StatisticsPanel(); self.individual.addWidget(self.statistics); self.individual.setSizes([230,990,280])
        batch=QWidget(); bl=QVBoxLayout(batch); self.mode.addTab(batch,'Procesamiento por lotes')
        br=QHBoxLayout(); bl.addLayout(br)
        for text,fn in [('+ DEMs',self.batch_add),('+ Carpeta',self.batch_folder),('Importar CSV',self.batch_csv),('Validar lote',self.batch_validate),('Quitar fila',self.batch_remove)]:
            b=QPushButton(text); b.clicked.connect(fn); br.addWidget(b)
        br.addStretch(); br.addWidget(QLabel('Trabajadores:')); self.parallel=QSpinBox(); self.parallel.setRange(1,8); self.parallel.setValue(1); br.addWidget(self.parallel)
        self.batch_table=QTableWidget(0,5); self.batch_table.setHorizontalHeaderLabels(['DEM','Máscara (doble clic)','Estado','Progreso','Salida']); self.batch_table.cellDoubleClicked.connect(self.batch_mask); bl.addWidget(self.batch_table)
        self.batch_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        bl.addWidget(QLabel('CSV: columnas dem,mask. Rutas relativas al CSV. El lote reutiliza exactamente el workflow inferior.'))
        pipeline_holder=QWidget(); pl=QVBoxLayout(pipeline_holder); pl.setContentsMargins(0,0,0,0)
        self.pipeline_holder=pipeline_holder; self.pipeline_layout=pl; self.graph_window=None
        heading=QHBoxLayout(); title=QLabel('FLUJO DE PROCESAMIENTO'); title.setObjectName('section'); heading.addWidget(title); heading.addStretch()
        self.detach_button=QPushButton('Abrir flujo en otra ventana'); self.detach_button.clicked.connect(self.toggle_graph_window); heading.addWidget(self.detach_button); pl.addLayout(heading)
        self.pipeline=PipelinePanel(); pl.addWidget(self.pipeline); vertical.addWidget(pipeline_holder); vertical.setSizes([460,440])
        outputbar=QHBoxLayout(); outer.addLayout(outputbar); outputbar.addWidget(QLabel('Carpeta de salida:'))
        self.output_path=QLineEdit(); self.output_path.setReadOnly(True); self.output_path.setAccessibleName('Carpeta de salida'); outputbar.addWidget(self.output_path,1)
        self.choose_output=QPushButton('Elegir carpeta…'); self.choose_output.clicked.connect(self.choose_output_directory); outputbar.addWidget(self.choose_output)
        self.reset_output=QPushButton('Usar proyecto'); self.reset_output.clicked.connect(self.reset_output_directory); outputbar.addWidget(self.reset_output)
        self.folder=QPushButton('Abrir salida'); self.folder.clicked.connect(self.open_output_directory); outputbar.addWidget(self.folder)
        self.output_path.setToolTip('Los archivos exportados se organizan por categoría y ejecución. Los temporales y registros permanecen en el proyecto.')
        runbar=QHBoxLayout(); outer.addLayout(runbar); runbar.addWidget(QLabel('Exportación:')); self.policy=QComboBox()
        for label,key in [('Ninguno','none'),('Finales','final'),('Detallado','detailed')]:self.policy.addItem(label,key)
        self.policy.setCurrentIndex(self.policy.findData(self.project.workflow.export_policy)); runbar.addWidget(self.policy)
        self.naming=QPushButton('Prefijo / sufijo'); self.naming.clicked.connect(self.configure_names); runbar.addWidget(self.naming)
        self.progress=QProgressBar(); self.progress.setRange(0,100); runbar.addWidget(self.progress,1)
        self.run_button=QPushButton('▶ Ejecutar'); self.run_button.setObjectName('run'); self.run_button.clicked.connect(self.execute); runbar.addWidget(self.run_button)
        self.cancel_button=QPushButton('■ Cancelar'); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self.cancel); runbar.addWidget(self.cancel_button)
        self.log=QTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(85); self.log.setPlaceholderText('Registro de ejecución, advertencias y errores'); outer.addWidget(self.log)
        self.layers.selected.connect(self.select_layer); self.layers.visibility_changed.connect(lambda:self.map.draw_layers(self.project.layers,True)); self.map.message.connect(self.statusBar().showMessage)
        self.layers.remove_requested.connect(self.remove_selected_layers); self.remove_layers_button.clicked.connect(self.remove_selected_layers)
        self.layers.restore_requested.connect(self.restore_layers); self.undo_layers_button.clicked.connect(self.restore_layers)
        self.layers.selection_count.connect(self.update_layer_actions)
        self.map.plotted_raster.connect(self.on_plotted_raster)
        self.pipeline.add_requested.connect(self.add_node); self.pipeline.edit_requested.connect(self.edit_node); self.pipeline.action_requested.connect(self.node_action); self.pipeline.template_requested.connect(self.template)
        self.create_menu(); self.refresh()

    def create_menu(self):
        for title,items in [('Archivo',[('Nuevo proyecto',self.new_project),('Abrir proyecto',self.open_project),('Guardar proyecto',self.save_project)]),
                            ('Workflow',[('Importar / reutilizar flujo…',self.load_workflow),('Exportar flujo completo…',self.export_workflow),('Entradas y variables…',self.configure_workflow),('Guardar JSON clásico',self.save_workflow)]),
                            ('Ayuda',[('Manual de uso',self.help)])]:
            menu=self.menuBar().addMenu(title)
            for text,fn in items:
                action=QAction(text,self); action.triggered.connect(fn); menu.addAction(action)

    def busy(self):return self.worker is not None and self.worker.isRunning()

    def sync(self):
        self.project.workflow.export_policy=self.policy.currentData(); self.project.vertical_unit=self.z_unit.currentText()

    def refresh(self):
        if self._view_project is not self.project:
            self._view_project=self.project; self.removed_layers.clear(); self.map.reset(); self.select_layer(None)
        self.project_label.setText(self.project.root.name+'   /   '+self.project.workflow.name)
        self.refresh_output_directory()
        self.layers.populate(self.project.layers,self.project.sources); self.map.draw_layers(self.project.layers,True)
        self.update_layer_actions(len(self.layers.selected_layers()))
        self.pipeline.show_workflow(self.project.workflow,self.statuses)

    def update_layer_actions(self,count):
        """Sincroniza contadores, botones y deshacer del árbol."""
        self.remove_layers_button.setText(f'Quitar ({count})'); self.remove_layers_button.setEnabled(count>0)
        self.undo_layers_button.setEnabled(bool(self.removed_layers)); self.layers.undo_action.setEnabled(bool(self.removed_layers))

    def remove_selected_layers(self):
        """Retira un grupo del proyecto sin borrar archivos ni referencias del DAG."""
        selected={id(l) for l in self.layers.selected_layers()}
        removed=[(i,l) for i,l in enumerate(self.project.layers) if id(l) in selected]
        if not removed:return
        previous=list(self.project.layers)
        self.project.layers=[l for l in previous if id(l) not in selected]
        try:self.sync(); self.project.save()
        except Exception as exc:
            self.project.layers=previous; self.inform(exc); return
        self.removed_layers.append(removed); self.removed_layers=self.removed_layers[-10:]
        if self.selected_layer and id(self.selected_layer) in selected:
            self.select_layer(next((l for l in reversed(self.project.layers) if l.visible and l.kind=='raster'),None))
        self.refresh()
        self.statusBar().showMessage(f'{len(removed)} capas retiradas. Archivos y entradas del flujo conservados. Puede deshacer.')

    def restore_layers(self):
        """Restaura orden y estilo del último grupo retirado, hasta diez acciones."""
        if not self.removed_layers:return
        previous=list(self.project.layers); removed=self.removed_layers[-1]
        for index,layer in removed:
            if not any(l is layer for l in self.project.layers):self.project.layers.insert(min(index,len(self.project.layers)),layer)
        try:self.project.save()
        except Exception as exc:
            self.project.layers=previous; self.inform(exc); return
        self.removed_layers.pop(); self.refresh()
        self.statusBar().showMessage(f'{len(removed)} capas restauradas.')

    def refresh_output_directory(self):
        self.output_path.setText(str(self.project.output_root)); self.output_path.setCursorPosition(0)
        self.reset_output.setEnabled(bool(self.project.output_directory) and not self.busy())

    def choose_output_directory(self):
        if self.busy():return
        path=QFileDialog.getExistingDirectory(self,'Elegir carpeta para los resultados',str(self.project.output_root))
        if path:
            previous=self.project.output_directory
            try:
                self.project.output_directory=str(Path(path).resolve())
                self.project.validate_output_directory()
                self.sync(); self.project.save(); self.refresh_output_directory()
            except Exception as exc:
                self.project.output_directory=previous; self.inform(exc)

    def reset_output_directory(self):
        if self.busy():return
        previous=self.project.output_directory
        try:
            self.project.output_directory=None; self.sync(); self.project.save(); self.refresh_output_directory()
        except Exception as exc:
            self.project.output_directory=previous; self.inform(exc)

    def open_output_directory(self):
        try:
            self.project.output_root.mkdir(parents=True,exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.output_root)))
        except Exception as exc:self.inform(exc)

    def inform(self,text):QMessageBox.warning(self,'DEM Workflows',str(text))

    def on_plotted_raster(self,layer):
        current=self.selected_layer
        if current and any(l is current for l in self.project.layers) and current.visible:
            self.statistics.show_layer(current)
        else:self.select_layer(layer)

    def toggle_graph_window(self):
        if self.graph_window and self.graph_window.isVisible():self.graph_window.close(); return
        if self.graph_window is None:
            self.graph_window=WorkflowWindow(self); self.graph_window.reattach.connect(self.attach_graph)
        self.pipeline_layout.removeWidget(self.pipeline)
        self.graph_window.content.addWidget(self.pipeline)
        self.pipeline_holder.setMaximumHeight(55)
        self.detach_button.setText('Volver a acoplar el flujo')
        self.graph_window.show(); self.pipeline.show(); self.pipeline.fit()

    def attach_graph(self):
        self.graph_window.content.removeWidget(self.pipeline); self.pipeline_layout.addWidget(self.pipeline)
        self.pipeline_holder.setMaximumHeight(16777215)
        self.pipeline_holder.parentWidget().setSizes([460,440])
        self.pipeline.show(); self.detach_button.setText('Abrir flujo en otra ventana')

    def add_dem(self):
        if self.busy():return
        path,_=QFileDialog.getOpenFileName(self,'Abrir DEM','','Raster (*.tif *.tiff *.img *.asc)')
        if path:self.load_dem(path)

    def load_dem(self,path):
        try:
            import rasterio
            with rasterio.open(path) as src:
                if src.count!=1:self.log.append('Raster multibanda: use Extraer banda antes de los procesos DEM.')
                if not src.crs:self.log.append('Advertencia: DEM sin CRS; asigne el CRS conocido antes de procesar.')
            layer=Layer(path,temporary=False,metadata={'vertical_unit':self.z_unit.currentText()})
            self.project.sources['$dem']=layer.path
            alias='$raster_'+str(len([k for k in self.project.sources if k.startswith('$raster_')])+1)
            if layer.path not in [v for k,v in self.project.sources.items() if k!='$dem']:
                self.project.sources[alias]=layer.path
            if layer.path not in [l.path for l in self.project.layers]:self.project.layers.append(layer)
            else:layer=next(l for l in self.project.layers if l.path==layer.path)
            self.refresh(); self.select_layer(layer)
        except Exception as exc:self.inform(exc)

    def add_vector(self):
        if self.busy():return
        path,_=QFileDialog.getOpenFileName(self,'Abrir vector / máscara','','Vector (*.gpkg *.shp *.geojson)')
        if path:
            try:
                import pyogrio
                info=pyogrio.read_info(path,force_feature_count=True)
                if info['features']==0 or not info['crs']:raise ValueError('Vector vacío o sin CRS.')
                layer=Layer(path,kind='vector',temporary=False); self.project.layers.append(layer)
                self.project.sources['$point' if info['geometry_type'] in ('Point','Point Z') else '$mask']=layer.path
                self.refresh(); self.select_layer(layer)
            except Exception as exc:self.inform(exc)

    def select_layer(self,layer):
        self.selected_layer=layer; self.map.selected=layer; self.statistics.show_layer(layer)

    def symbology(self):
        if self.selected_layer:
            dialog=StyleDialog(self.selected_layer,self)
            if dialog.exec()==QDialog.DialogCode.Accepted:
                self.selected_layer.style=dialog.result_style; self.map.draw_layers(self.project.layers,True); self.statistics.show_layer(self.selected_layer)

    def export_selected(self):
        if not self.selected_layer:return
        layer=self.selected_layer; extension=Path(layer.path).suffix
        path,_=QFileDialog.getSaveFileName(self,'Exportar capa',str(self.project.output_root/(layer.name+extension)),f'Archivo (*{extension})')
        if path:
            try:export_layer(layer,path); self.log.append('Exportado: '+path)
            except Exception as exc:self.inform(exc)

    def configure_names(self):
        if self.busy():return
        prefix,ok=QInputDialog.getText(self,'Nomenclatura','Prefijo:',text=self.project.workflow.prefix)
        if not ok:return
        suffix,ok=QInputDialog.getText(self,'Nomenclatura','Sufijo:',text=self.project.workflow.suffix)
        if ok:self.project.workflow.prefix=prefix; self.project.workflow.suffix=suffix

    def node_dialog(self,node,is_new=False):
        if self.busy():return
        dialog=NodeDialog(node,self.project.workflow,self.project.sources,self.graph_window if self.graph_window and self.graph_window.isVisible() else self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            updated=dialog.result_node
            self.project.sources.update(dialog.new_sources)
            for key,path in dialog.new_sources.items():
                if path not in [l.path for l in self.project.layers]:self.project.layers.append(Layer(path,kind='vector',temporary=False,visible=False))
            if is_new:self.project.workflow.nodes.append(updated)
            else:self.project.workflow.nodes=[updated if n.id==node.id else n for n in self.project.workflow.nodes]
            self.statuses={}; self.pipeline.show_workflow(self.project.workflow)
            if dialog.preview_requested:self.execute(preview=updated.id)

    def add_node(self,algorithm):
        ports=self.registry[algorithm].ports
        selected=self.pipeline.selection()
        inputs={k:(selected or ('$mask' if k in ('mask','vector') else '$point' if k=='point' else '$dem')) for k in ports}
        self.node_dialog(ProcessingNode(algorithm,inputs=inputs),True)

    def edit_node(self,id):
        node=next((n for n in self.project.workflow.nodes if n.id==id),None)
        if node:self.node_dialog(node)

    def node_action(self,action,id):
        if self.busy():return
        nodes=self.project.workflow.nodes; index=next(i for i,n in enumerate(nodes) if n.id==id); node=nodes[index]
        if action=='edit':self.edit_node(id); return
        if action=='delete':
            dependencies=[n.name for n in nodes if id in n.inputs.values()]
            if dependencies:self.inform('Desconecte primero los nodos dependientes: '+', '.join(dependencies)); return
            nodes.pop(index)
        elif action=='duplicate':nodes.insert(index+1,replace(node,id=uuid.uuid4().hex[:12],name=node.name+'_copia',inputs=dict(node.inputs),parameters=json.loads(json.dumps(node.parameters))))
        elif action=='toggle':node.enabled=not node.enabled
        elif action in ('up','down'):
            other=index+(-1 if action=='up' else 1)
            if 0<=other<len(nodes):nodes[index],nodes[other]=nodes[other],nodes[index]
        self.statuses={}; self.pipeline.show_workflow(self.project.workflow)

    def template(self,name):
        if self.busy():return
        if name=='Microcuencas por tramos D8':
            dialog=MicrobasinsDialog(self.project.sources,self)
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            if self.project.workflow.nodes and QMessageBox.question(self,'Plantilla','¿Reemplazar el workflow actual por la plantilla configurada?')!=QMessageBox.StandardButton.Yes:return
            self.project.workflow=dialog.result_workflow; self.project.sources.update(dialog.result_sources)
            for key,path in dialog.result_sources.items():
                if path not in [l.path for l in self.project.layers]:self.project.layers.append(Layer(path,kind='raster' if key=='$dem' else 'vector',temporary=False))
            self.policy.setCurrentIndex(self.policy.findData('final')); self.statuses={}; self.refresh(); self.pipeline.fit(); return
        if name in ('Relieve básico','Hidrología D8'):
            if self.project.workflow.nodes and QMessageBox.question(self,'Plantilla','¿Reemplazar el workflow actual?')!=QMessageBox.StandardButton.Yes:return
            if name=='Relieve básico':
                crs,ok=QInputDialog.getText(self,'CRS de trabajo','CRS proyectado apropiado para el área:',text='EPSG:32718')
                if not ok:return
                self.project.workflow=relief_template(crs)
            else:self.project.workflow=hydrology_template()
        else:
            source=self.pipeline.selection() or '$dem'
            if name=='TPI multiescala':
                text,ok=QInputDialog.getText(self,'TPI multiescala','Radios en metros separados por ;',text='100;500;1000')
                if not ok:return
                try:
                    radii=[float(r.strip()) for r in text.split(';')]
                    if not radii or min(radii)<=0:raise ValueError('Radios positivos requeridos.')
                    self.project.workflow.nodes.extend(ProcessingNode('tpi',inputs={'dem':source},parameters={'radius':r,'unit':'meters'},name=f'TPI_{r:g}m') for r in radii)
                except Exception as exc:self.inform(exc); return
            elif name=='Tres curvaturas':
                self.project.workflow.nodes.extend(ProcessingNode('curvature',inputs={'dem':source},parameters={'kind':k},name='curv_'+k) for k in ('general','profile','plan'))
        self.policy.setCurrentIndex(self.policy.findData(self.project.workflow.export_policy)); self.statuses={}; self.refresh(); self.pipeline.fit()

    def execute(self,checked=False,preview=None):
        if self.busy():return
        self.sync()
        if not self.project.workflow.nodes:self.inform('Añade procesos al flujo.'); return
        if self.mode.currentIndex()==0 and '$dem' not in self.project.sources:self.inform('Carga un DEM.'); return
        try:
            self.project.workflow.ordered(); self.project.save()
            snapshot=Project(self.project.root,Workflow.from_dict(asdict(self.project.workflow)),dict(self.project.sources),vertical_unit=self.project.vertical_unit,output_directory=self.project.output_directory)
            if preview:
                ids={preview}; changed=True
                while changed:
                    old=len(ids); ids.update(r for n in snapshot.workflow.nodes if n.id in ids for r in n.inputs.values() if not r.startswith('$')); changed=len(ids)!=old
                snapshot.workflow.nodes=[replace(n,export='temporary') for n in snapshot.workflow.nodes if n.id in ids]; snapshot.workflow.export_policy='none'
            batch=self.mode.currentIndex()==1 and not preview
            if batch:
                if not self.batch_items:raise ValueError('Añade DEMs al lote.')
                validation=validate_batch(self.batch_items,snapshot.workflow)
                invalid=[m for _,ok,m in validation if not ok]
                if invalid:raise ValueError('\n'.join(invalid))
            self.statuses={}; self.batch_states={}; self.progress.setValue(0); self.log.append('Inicio de ejecución. '+('Vista previa: nodo y dependencias.' if preview else ''))
            self.worker=Worker(snapshot,list(self.batch_items) if batch else None,self.parallel.value())
            self.worker.event.connect(self.on_event); self.worker.completed.connect(self.on_complete); self.worker.failed.connect(self.on_failure); self.worker.finished.connect(self.unlock)
            self.run_button.setEnabled(False); self.cancel_button.setEnabled(True); self.pipeline.setEnabled(False); self.policy.setEnabled(False); self.z_unit.setEnabled(False); self.mode.tabBar().setEnabled(False)
            self.choose_output.setEnabled(False); self.reset_output.setEnabled(False)
            self.worker.start()
        except Exception as exc:self.inform(exc)

    def cancel(self):
        if self.worker:self.worker.cancel.set(); self.log.append('Cancelación solicitada; esperando fin de la operación nativa en curso.')

    def unlock(self):
        self.run_button.setEnabled(True); self.cancel_button.setEnabled(False); self.pipeline.setEnabled(True); self.policy.setEnabled(True); self.z_unit.setEnabled(True); self.mode.tabBar().setEnabled(True)
        self.choose_output.setEnabled(True); self.refresh_output_directory()

    def on_event(self,row,id,status,message):
        self.log.append(f'{"Lote "+str(row+1)+" · " if row>=0 else ""}{id}: {status}'+(' · '+message if message else ''))
        finished=('Completed','Warning','Error','Blocked','Cancelled')
        if row<0:
            self.statuses[id]=status; self.pipeline.show_workflow(self.project.workflow,self.statuses)
            self.progress.setValue(int(100*sum(s in finished for s in self.statuses.values())/max(1,len(self.worker.project.workflow.nodes))))
        else:
            self.batch_states[(row,id)]=status
            completed=sum(s in finished for (r,_),s in self.batch_states.items() if r==row)
            self.batch_table.setItem(row,2,QTableWidgetItem(status)); self.batch_table.setItem(row,3,QTableWidgetItem(f'{int(100*completed/max(1,len(self.project.workflow.nodes)))} %'))
            self.progress.setValue(int(100*sum(s in finished for s in self.batch_states.values())/max(1,len(self.batch_items)*len(self.project.workflow.nodes))))

    def on_complete(self,report):
        if isinstance(report,dict):
            for row,result in report.items():
                self.batch_table.setItem(row,2,QTableWidgetItem(result['status'])); self.batch_table.setItem(row,4,QTableWidgetItem(result.get('output','')))
            self.log.append('Lote finalizado; consulte batch_report.json y los proyectos de cada fila.')
        else:
            existing={l.path for l in self.project.layers}
            for layer in report.results.values():
                if layer.path not in existing:self.project.layers.append(layer); existing.add(layer.path)
                for path in layer.metadata.get('artifacts',[]):
                    kind='raster' if path.endswith('.tif') else 'vector' if path.endswith('.gpkg') else 'table'
                    if path not in existing:self.project.layers.append(Layer(path,kind=kind,visible=False)); existing.add(path)
            for path in report.exports:
                if path not in existing:
                    kind='raster' if path.endswith('.tif') else 'vector' if path.endswith('.gpkg') else 'table'
                    self.project.layers.append(Layer(path,kind=kind,temporary=False,visible=False)); existing.add(path)
            self.refresh()
            self.log.append(f'{len(report.results)} resultados · {len(report.cache_hits)} reutilizados · {len(report.exports)} exportados · {len(report.errors)} errores. Log: {report.log}')
        self.project.save()

    def on_failure(self,message):self.log.append('ERROR: '+message); self.inform(message)

    def save_project(self):
        if self.busy():return
        try:self.sync(); self.project.save(); self.statusBar().showMessage('Proyecto guardado: '+str(self.project.root/'project.json'))
        except Exception as exc:self.inform(exc)

    def new_project(self):
        if self.busy():return
        path=QFileDialog.getExistingDirectory(self,'Carpeta para nuevo proyecto')
        if path:
            if (Path(path)/'project.json').exists():self.inform('Ya existe un proyecto aquí; use Abrir proyecto.'); return
            self.save_project(); self.project=Project(path); self.statuses={}; self.refresh()

    def open_project(self):
        if self.busy():return
        path,_=QFileDialog.getOpenFileName(self,'Abrir proyecto','','Proyecto (project.json)')
        if path:
            try:
                self.save_project(); self.project=Project.load(path); self.z_unit.setCurrentText(self.project.vertical_unit); self.policy.setCurrentIndex(self.policy.findData(self.project.workflow.export_policy)); self.statuses={}; self.refresh()
            except Exception as exc:self.inform(exc)

    def apply_workflow_bindings(self,dialog):
        self.project.workflow=dialog.result_workflow
        self.project.sources.update(dialog.result_sources)
        self.project.vertical_unit=dialog.result_unit; self.z_unit.setCurrentText(dialog.result_unit)
        for layer in self.project.layers:layer.visible=False
        for key,path in dialog.result_sources.items():
            existing=next((l for l in self.project.layers if l.path==path),None)
            if existing:existing.visible=True
            else:
                self.project.layers.append(Layer(path,kind=dialog.variables[key]['kind'],temporary=False))
        self.policy.setCurrentIndex(self.policy.findData(self.project.workflow.export_policy)); self.statuses={}; self.refresh()

    def configure_workflow(self):
        if self.busy():return
        self.sync()
        dialog=WorkflowVariablesDialog(self.project.workflow,self.project.sources,self.project.vertical_unit,parent=self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_workflow_bindings(dialog)

    def export_workflow(self):
        if self.busy():return
        self.sync(); path,_=QFileDialog.getSaveFileName(self,'Exportar flujo completo',str(self.project.root/'workflows'/'flujo.demflow.json'),'Flujo reutilizable (*.demflow.json)')
        if path:
            try:
                export_bundle(path,self.project.workflow,self.project.sources,self.project.vertical_unit)
                self.log.append('Flujo completo exportado. Los insumos se reasignan al importar: '+path)
            except Exception as exc:self.inform(exc)

    def load_workflow(self):
        if self.busy():return
        path,_=QFileDialog.getOpenFileName(self,'Importar / reutilizar flujo','','Flujos (*.json)')
        if path:
            try:
                workflow,variables,unit=load_bundle(path)
                dialog=WorkflowVariablesDialog(workflow,self.project.sources,unit,variables,self)
                if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_workflow_bindings(dialog)
            except Exception as exc:self.inform(exc)

    def save_workflow(self):
        self.sync(); path,_=QFileDialog.getSaveFileName(self,'Guardar workflow',str(self.project.root/'workflows'/'workflow.json'),'JSON (*.json)')
        if path:
            try:self.project.workflow.save(path)
            except Exception as exc:self.inform(exc)

    def batch_refresh(self):
        self.batch_table.setRowCount(len(self.batch_items))
        for r,item in enumerate(self.batch_items):
            for c,text in enumerate([item.dem,item.mask,'En espera','0 %','']):self.batch_table.setItem(r,c,QTableWidgetItem(text))
        self.batch_table.resizeColumnsToContents()

    def batch_add(self):
        if self.busy():return
        paths,_=QFileDialog.getOpenFileNames(self,'DEMs del lote','','GeoTIFF (*.tif *.tiff)')
        self.batch_items.extend(BatchItem(p) for p in paths); self.batch_refresh()

    def batch_folder(self):
        if self.busy():return
        path=QFileDialog.getExistingDirectory(self,'Carpeta de DEMs')
        if path:self.batch_items.extend(BatchItem(str(p)) for p in sorted(Path(path).iterdir()) if p.suffix.lower() in ('.tif','.tiff')); self.batch_refresh()

    def batch_csv(self):
        if self.busy():return
        path,_=QFileDialog.getOpenFileName(self,'Tabla de lotes','','CSV (*.csv)')
        if path:
            try:self.batch_items.extend(import_csv(path)); self.batch_refresh()
            except Exception as exc:self.inform(exc)

    def batch_mask(self,row,col):
        if self.busy():return
        if col==1:
            path,_=QFileDialog.getOpenFileName(self,'Máscara de esta fila','','Vector (*.gpkg *.shp *.geojson)')
            if path:self.batch_items[row].mask=path; self.batch_refresh()
        elif col==4:
            item=self.batch_table.item(row,col)
            if item and item.text():QDesktopServices.openUrl(QUrl.fromLocalFile(item.text()))

    def batch_remove(self):
        if self.busy():return
        row=self.batch_table.currentRow()
        if row>=0:self.batch_items.pop(row); self.batch_refresh()

    def batch_validate(self):
        if self.busy():return
        for i,ok,message in validate_batch(self.batch_items,self.project.workflow):self.batch_table.setItem(i,2,QTableWidgetItem(message))

    def help(self):QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(__file__).parents[2]/'docs'/'MANUAL_DE_USUARIO.html')))

    def closeEvent(self,event):
        if self.busy():
            self.cancel(); self.statusBar().showMessage('Espere que termine la cancelación antes de cerrar.'); event.ignore(); return
        try:self.sync(); self.project.save()
        except Exception as exc:self.inform(exc); event.ignore(); return
        temporaries=[l for l in self.project.layers if l.temporary]
        if temporaries:
            answer=QMessageBox.question(self,'Resultados temporales','¿Eliminar resultados temporales? Los resultados exportados se conservan.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer==QMessageBox.StandardButton.Yes:
                root=self.project.root.resolve(); target=(root/'temporary').resolve()
                if target.parent==root and target.name=='temporary':shutil.rmtree(target); target.mkdir()
                self.project.layers=[l for l in self.project.layers if not l.temporary]; self.project.save()
        event.accept()
        if self.graph_window:self.graph_window.hide()
