from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QAction,QKeySequence
from PySide6.QtWidgets import QTreeWidget,QTreeWidgetItem,QAbstractItemView,QMenu


class LayerPanel(QTreeWidget):
    selected=Signal(object)
    visibility_changed=Signal()
    remove_requested=Signal()
    restore_requested=Signal()
    selection_count=Signal(int)
    def __init__(self):
        super().__init__()
        self.setHeaderLabels(['CAPAS / RESULTADOS'])
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformRowHeights(True)
        self.setToolTip('Ctrl: seleccionar varias · Mayús: seleccionar rango · Supr: quitar del mapa · Ctrl+Z: deshacer')
        self.remove_action=QAction('Quitar capas seleccionadas',self)
        self.remove_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.undo_action=QAction('Deshacer retiro de capas',self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setEnabled(False)
        for action in (self.remove_action,self.undo_action):
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut); self.addAction(action)
        self.remove_action.triggered.connect(self.remove_requested.emit)
        self.undo_action.triggered.connect(self.restore_requested.emit)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)
        self.itemSelectionChanged.connect(self.selection)
        self.itemChanged.connect(self.changed)

    def populate(self,layers,sources):
        selected={id(l) for l in self.selected_layers()}
        current=self.currentItem().data(0,Qt.ItemDataRole.UserRole) if self.currentItem() else None
        collapsed={self.topLevelItem(i).text(0) for i in range(self.topLevelItemCount()) if not self.topLevelItem(i).isExpanded()}
        self.blockSignals(True); self.clear()
        groups={k:QTreeWidgetItem(self,[k]) for k in ('ENTRADAS','TEMPORALES','RESULTADOS')}
        for item in groups.values():item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for layer in reversed(layers):
            group='ENTRADAS' if layer.path in sources.values() else 'TEMPORALES' if layer.temporary else 'RESULTADOS'
            item=QTreeWidgetItem(groups[group],[('▧ ' if layer.kind=='raster' else '◇ ')+layer.name])
            item.setData(0,Qt.ItemDataRole.UserRole,layer)
            item.setCheckState(0,Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            item.setToolTip(0,layer.path)
            if layer is current:self.setCurrentItem(item,0,self.selectionModel().SelectionFlag.NoUpdate)
            if id(layer) in selected:item.setSelected(True)
        for name,item in groups.items():item.setExpanded(name not in collapsed)
        self.blockSignals(False); self.selection()

    def selected_layers(self):
        """Obtiene únicamente las capas seleccionadas; excluye cabeceras de grupos."""
        return [layer for item in self.selectedItems() if (layer:=item.data(0,Qt.ItemDataRole.UserRole)) is not None]

    def context_menu(self,position):
        """Ofrece acciones colectivas conservando una selección múltiple existente."""
        item=self.itemAt(position)
        if item and item.data(0,Qt.ItemDataRole.UserRole) and not item.isSelected():
            self.clearSelection(); self.setCurrentItem(item); item.setSelected(True)
        menu=QMenu(self); menu.addAction(self.remove_action); menu.addAction(self.undo_action); menu.addSeparator()
        for label,visible in [('Mostrar seleccionadas',True),('Ocultar seleccionadas',False)]:
            action=menu.addAction(label); action.setEnabled(bool(self.selected_layers()))
            action.triggered.connect(lambda checked=False,v=visible:self.set_selected_visible(v))
        menu.addSeparator(); menu.addAction('Seleccionar todas',self.selectAll)
        menu.exec(self.viewport().mapToGlobal(position))

    def set_selected_visible(self,visible):
        """Cambia varias casillas y solicita un único refresco del mapa."""
        self.blockSignals(True)
        for item in self.selectedItems():
            layer=item.data(0,Qt.ItemDataRole.UserRole)
            if layer:
                layer.visible=visible; item.setCheckState(0,Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked)
        self.blockSignals(False); self.visibility_changed.emit()

    def selection(self):
        count=len(self.selected_layers()); self.remove_action.setEnabled(bool(count)); self.selection_count.emit(count)
        if self.currentItem():
            layer=self.currentItem().data(0,Qt.ItemDataRole.UserRole)
            if layer and self.currentItem().isSelected(): self.selected.emit(layer)

    def changed(self,item,column):
        layer=item.data(0,Qt.ItemDataRole.UserRole)
        if layer:
            layer.visible=item.checkState(0)==Qt.CheckState.Checked
            self.visibility_changed.emit()
