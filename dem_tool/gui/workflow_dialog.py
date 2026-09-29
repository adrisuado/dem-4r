from dataclasses import asdict
from pathlib import Path
import json
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,
    QDialogButtonBox,QTabWidget,QWidget,QFormLayout,QScrollArea,QComboBox,QFileDialog,
    QTableWidget,QTableWidgetItem,QMessageBox,QHeaderView)
from dem_tool.core.models import Workflow
from dem_tool.core.workflow_bundle import input_variables
from dem_tool.algorithms import load_algorithms


class WorkflowVariablesDialog(QDialog):
    def __init__(self,workflow,sources,vertical_unit='m',variables=None,parent=None):
        super().__init__(parent); self.setWindowTitle('Reutilizar flujo · entradas y variables'); self.resize(900,640)
        self.workflow=Workflow.from_dict(asdict(workflow)); self.result_sources={}; self.fields={}
        self.variables=variables or input_variables(workflow)
        layout=QVBoxLayout(self); title=QLabel(workflow.name); title.setObjectName('section'); layout.addWidget(title)
        note=QLabel('Reemplaza los insumos una sola vez. Se conservan todos los nodos, conexiones y políticas de salida. Los parámetros pueden ajustarse en la segunda pestaña.'); note.setWordWrap(True); layout.addWidget(note)
        tabs=QTabWidget(); layout.addWidget(tabs)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); body=QWidget(); form=QFormLayout(body); scroll.setWidget(body); tabs.addTab(scroll,'Entradas del flujo')
        self.z_unit=QComboBox(); self.z_unit.addItems(['m','ft','us-ft']); self.z_unit.setCurrentText(vertical_unit); form.addRow('Unidad vertical de los DEM',self.z_unit)
        for key,info in self.variables.items():
            row=QWidget(); line=QHBoxLayout(row); line.setContentsMargins(0,0,0,0)
            field=QLineEdit(sources.get(key,'')); field.setPlaceholderText(info.get('file_hint','Elegir archivo…')); field.setToolTip('\n'.join(info['used_by'])); line.addWidget(field)
            button=QPushButton('Examinar…'); button.clicked.connect(lambda checked=False,k=key:self.browse(k)); line.addWidget(button)
            self.fields[key]=field; form.addRow(f'{key} · {info["kind"]}'+(' *' if info['required'] else ''),row)
        parameters=QWidget(); pv=QVBoxLayout(parameters); tabs.addTab(parameters,'Parámetros reutilizables')
        pv.addWidget(QLabel('Edita valores; listas y tablas usan JSON. Los tipos y rangos se validan al ejecutar cada algoritmo.'))
        self.parameters=QTableWidget(0,3); self.parameters.setHorizontalHeaderLabels(['Proceso','Parámetro','Valor']); self.parameters.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch); pv.addWidget(self.parameters)
        self.param_rows=[]; registry=load_algorithms()
        from PySide6.QtCore import Qt
        for node in self.workflow.nodes:
            for key,value in (registry[node.algorithm].defaults|node.parameters).items():
                row=self.parameters.rowCount(); self.parameters.insertRow(row)
                for col,text in enumerate([node.name,key,value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)]):
                    item=QTableWidgetItem(text)
                    if col<2:item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.parameters.setItem(row,col,item)
                self.param_rows.append((node,key,value))
        self.parameters.resizeColumnsToContents()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.apply); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def browse(self,key):
        vector=self.variables[key]['kind']=='vector'
        path,_=QFileDialog.getOpenFileName(self,'Entrada '+key,'','Vector (*.gpkg *.shp *.geojson)' if vector else 'Raster (*.tif *.tiff *.img *.asc)')
        if path:self.fields[key].setText(path)

    def build(self):
        import rasterio
        import geopandas as gpd
        sources={}
        for key,field in self.fields.items():
            value=field.text().strip(); info=self.variables[key]
            if not value and not info['required']:continue
            path=Path(value)
            if not value or not path.is_file():raise ValueError(f'{key}: seleccione un archivo existente.')
            if info['kind']=='raster':
                with rasterio.open(path) as src:
                    if src.count<1:raise ValueError(f'{key}: raster sin bandas.')
            else:
                frame=gpd.read_file(path)
                if frame.empty or not frame.crs:raise ValueError(f'{key}: vector vacío o sin CRS.')
            sources[key]=str(path.resolve())
        for row,(node,key,original) in enumerate(self.param_rows):
            text=self.parameters.item(row,2).text()
            value=text if isinstance(original,str) else json.loads(text)
            if isinstance(original,bool) and not isinstance(value,bool):raise ValueError(f'{key}: use true o false.')
            if isinstance(original,(int,float)) and not isinstance(original,bool) and (isinstance(value,bool) or not isinstance(value,(int,float))):raise ValueError(f'{key}: se requiere un número.')
            if isinstance(original,list) and not isinstance(value,list):raise ValueError(f'{key}: se requiere una lista JSON.')
            node.parameters[key]=value
        self.workflow.ordered()
        return self.workflow,sources,self.z_unit.currentText()

    def apply(self):
        try:
            self.result_workflow,self.result_sources,self.result_unit=self.build(); self.accept()
        except Exception as exc:QMessageBox.warning(self,'Variables del flujo',str(exc))
