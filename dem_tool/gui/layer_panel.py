from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import QTreeWidget,QTreeWidgetItem,QAbstractItemView


class LayerPanel(QTreeWidget):
    selected=Signal(object)
    visibility_changed=Signal()
    def __init__(self):
        super().__init__()
        self.setHeaderLabels(['CAPAS / RESULTADOS'])
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.itemSelectionChanged.connect(self.selection)
        self.itemChanged.connect(self.changed)

    def populate(self,layers,sources):
        self.blockSignals(True); self.clear()
        groups={k:QTreeWidgetItem(self,[k]) for k in ('ENTRADAS','TEMPORALES','RESULTADOS')}
        for layer in reversed(layers):
            group='ENTRADAS' if layer.path in sources.values() else 'TEMPORALES' if layer.temporary else 'RESULTADOS'
            item=QTreeWidgetItem(groups[group],[('▧ ' if layer.kind=='raster' else '◇ ')+layer.name])
            item.setData(0,Qt.ItemDataRole.UserRole,layer)
            item.setCheckState(0,Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            item.setToolTip(0,layer.path)
        self.expandAll(); self.blockSignals(False)

    def selection(self):
        if self.currentItem():
            layer=self.currentItem().data(0,Qt.ItemDataRole.UserRole)
            if layer: self.selected.emit(layer)

    def changed(self,item,column):
        layer=item.data(0,Qt.ItemDataRole.UserRole)
        if layer:
            layer.visible=item.checkState(0)==Qt.CheckState.Checked
            self.visibility_changed.emit()
