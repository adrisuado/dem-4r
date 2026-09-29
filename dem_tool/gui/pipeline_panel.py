from PySide6.QtCore import Qt,Signal,QRectF
from PySide6.QtGui import QColor,QPen,QBrush,QPainterPath,QPainter,QFont
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QComboBox,QGraphicsView,QGraphicsScene,QGraphicsRectItem,QGraphicsTextItem,QTableWidget,QTableWidgetItem,QTabWidget,QAbstractItemView,QToolButton,QMenu,QDialog
from dem_tool.algorithms import load_algorithms


COLORS={'Ready':'#8499ab','Running':'#eeb55e','Completed':'#4dd6ae','Warning':'#f4ce68','Error':'#ed7c80','Blocked':'#677080','Cancelled':'#b28be3'}


class WorkflowWindow(QDialog):
    reattach=Signal()
    def __init__(self,parent):
        super().__init__(parent)
        self.setWindowTitle('Flujo de procesamiento · ventana independiente')
        self.setWindowFlags(Qt.WindowType.Window|Qt.WindowType.WindowMinMaxButtonsHint|Qt.WindowType.WindowCloseButtonHint)
        self.resize(1350,750); self.content=QVBoxLayout(self)
        button=QPushButton('Volver a acoplar al mapa'); button.clicked.connect(self.close); self.content.addWidget(button)

    def closeEvent(self,event):
        self.reattach.emit(); event.accept()


class NodeBox(QGraphicsRectItem):
    def __init__(self,node,title,position,status,callback):
        super().__init__(0,0,205,86); self.setPos(*position); self.node=node; self.callback=callback
        self.setPen(QPen(QColor(COLORS[status]),1.5)); self.setBrush(QBrush(QColor('#203249')))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
        self.text=QGraphicsTextItem(self); text=self.text; text.setTextWidth(194); text.setDefaultTextColor(QColor('#dce8f2'))
        text.setFont(QFont('DejaVu Sans',9))
        text.setPlainText(f'{node.name[:27]}\n{title[:28]}\n{status} · {node.export}'); text.setPos(5,3)
        self.setToolTip(f'{node.id}\nEntradas: {node.inputs}\nParámetros: {node.parameters}')

    def mouseDoubleClickEvent(self,event):self.callback(self.node.id)


class PipelinePanel(QWidget):
    add_requested=Signal(str)
    edit_requested=Signal(str)
    action_requested=Signal(str,str)
    template_requested=Signal(str)
    def __init__(self):
        super().__init__(); layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        categories=QHBoxLayout(); self.category_buttons={}
        groups={'preprocessing':'Preprocesamiento','relief':'Relieve','hydrology':'Hidrología','raster_math':'Álgebra raster','vectors':'Vectores','tables':'Cuencas'}
        for category,title in groups.items():
            button=QToolButton(); button.setText('+ '+title); button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu=QMenu(button)
            for a in load_algorithms().values():
                if a.category==category:
                    action=menu.addAction(a.title); action.triggered.connect(lambda checked=False,id=a.id:self.add_requested.emit(id))
            button.setMenu(menu); self.category_buttons[category]=button; categories.addWidget(button)
        categories.addStretch(); layout.addLayout(categories)
        controls=QHBoxLayout()
        for title,action in [('Editar / conectar','edit'),('Duplicar','duplicate'),('Eliminar','delete'),('Activar','toggle'),('↑','up'),('↓','down')]:
            b=QPushButton(title); b.clicked.connect(lambda checked=False,a=action:self.action(a)); controls.addWidget(b)
        controls.addStretch(); self.template=QComboBox(); self.template.addItems(['Plantillas…','Relieve básico','Hidrología D8','TPI multiescala','Tres curvaturas']); self.template.activated.connect(lambda i:self.template_requested.emit(self.template.itemText(i)) if i else None); controls.addWidget(self.template)
        layout.addLayout(controls); self.tabs=QTabWidget(); layout.addWidget(self.tabs)
        self.scene=QGraphicsScene(); self.view=QGraphicsView(self.scene); self.view.setRenderHint(QPainter.RenderHint.Antialiasing); self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag); self.view.setBackgroundBrush(QColor('#101b2b')); self.tabs.addTab(self.view,'Grafo de dependencias')
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['Nodo','Proceso','Entradas','Exportación','Estado']); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.cellDoubleClicked.connect(lambda r,c:self.edit_requested.emit(self.table.item(r,0).data(Qt.ItemDataRole.UserRole))); self.tabs.addTab(self.table,'Nodos y conexiones')
        self.workflow=None; self.statuses={}
        zoom=QHBoxLayout()
        for title,callback in [('− Zoom',lambda:self.view.scale(.8,.8)),('+ Zoom',lambda:self.view.scale(1.25,1.25)),('Ajustar grafo',self.fit)]:
            b=QPushButton(title); b.clicked.connect(callback); zoom.addWidget(b)
        zoom.addStretch(); layout.addLayout(zoom)

    def selection(self):
        if self.tabs.currentIndex()==0:
            items=self.scene.selectedItems(); return items[0].node.id if items else ''
        r=self.table.currentRow(); return self.table.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 else ''

    def action(self,action):
        id=self.selection()
        if id:self.action_requested.emit(action,id)

    def show_workflow(self,workflow,statuses=None):
        self.workflow=workflow; self.statuses=statuses or {}; self.scene.clear(); self.table.setRowCount(0)
        try:ordered=workflow.ordered()
        except ValueError:ordered=workflow.nodes
        columns={}; positions={}; used={}
        for node in ordered:
            col=1+max([columns[r] for r in node.inputs.values() if r in columns] or [-1]); columns[node.id]=col
            row=used.get(col,0); used[col]=row+1; positions[node.id]=(col*255,row*112)
            status=self.statuses.get(node.id,'Ready' if node.enabled else 'Blocked')
            a=load_algorithms()[node.algorithm]
            self.scene.addItem(NodeBox(node,a.title,positions[node.id],status,self.edit_requested.emit))
            r=self.table.rowCount(); self.table.insertRow(r)
            for c,text in enumerate([node.name,a.title,str(node.inputs),node.export,status]):self.table.setItem(r,c,QTableWidgetItem(text))
            self.table.item(r,0).setData(Qt.ItemDataRole.UserRole,node.id)
        for node in ordered:
            for ref in node.inputs.values():
                if ref not in positions:continue
                x,y=positions[ref]; xx,yy=positions[node.id]
                path=QPainterPath(); path.moveTo(x+205,y+43); path.cubicTo(x+232,y+43,xx-27,yy+43,xx,yy+43)
                self.scene.addPath(path,QPen(QColor('#4bbdac'),2)).setZValue(-1)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-25,-20,25,20)); self.table.resizeColumnsToContents()

    def fit(self):
        self.view.fitInView(self.scene.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
        self.view.horizontalScrollBar().setValue(self.view.horizontalScrollBar().minimum())
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().minimum())
