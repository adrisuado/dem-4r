import csv
import json
from dataclasses import replace
from pathlib import Path
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QDialogButtonBox,
    QLabel,QLineEdit,QComboBox,QCheckBox,QSpinBox,QDoubleSpinBox,QScrollArea,QWidget,
    QTableWidget,QTableWidgetItem,QPushButton,QFileDialog,QMessageBox)
from dem_tool.algorithms import load_algorithms
from dem_tool.algorithms.raster_math import validate_expression
from dem_tool.core.models import Symbology

LABELS={'method':'Método','radius':'Radio','iterations':'Iteraciones','max_gap':'Tamaño máximo del gap (píxeles)',
    'keep_large':'Conservar huecos mayores','kernel':'Kernel (lado impar)','sigma':'Sigma','nodata':'Tratamiento NoData',
    'vertical_unit':'Unidad vertical','z_factor':'Factor Z adicional','edges':'Bordes','units':'Unidad de salida',
    'unit':'Unidad de escala / umbral','shape':'Forma de vecindad','standardize':'Estandarizar TPI',
    'crs':'CRS de destino','resolution':'Resolución destino (0 = automática)','resampling':'Remuestreo',
    'bounds':'Extensión [xmin,ymin,xmax,ymax]','kind':'Tipo de curvatura','azimuth':'Azimut solar (°)',
    'altitude':'Altitud solar (°)','expression':'Expresión','threshold':'Umbral contribuyente',
    'vector':'Generar drenaje vectorial','strahler':'Generar orden Strahler','shreve':'Generar magnitud Shreve','resolve_flats':'Resolver planos',
    'epsilon':'Incremento mínimo de planos (m)','max_depth':'Profundidad máxima (m; 0 = sin límite)',
    'buffer_m':'Buffer de máscara (m)','distance_m':'Distancia (m)','max_distance_m':'Tolerancia máxima (m)',
    'field':'Campo de disolución','connectivity':'Conectividad','unmatched':'Valores no cubiertos',
    'factor':'Factor multiplicador','output_unit':'Unidad vertical resultante','value':'Valor a convertir en NoData',
    'x':'Coordenada X','y':'Coordenada Y','products':'Productos (lista JSON)','packaging':'Empaquetado','band':'Número de banda'}
CHOICES={'vertical_unit':['inherit','m','ft','us-ft'],'output_unit':['m','ft','us-ft'],
    'packaging':['separate','multiband','both'],
    'edges':['nodata','local'],'shape':['circle','square'],'resampling':['nearest','bilinear','cubic','average'],
    'kind':['general','profile','plan','tangential'],'nodata':['ignore','propagate'],'unmatched':['nodata','keep']}


class RulesTable(QWidget):
    def __init__(self,rules):
        super().__init__(); layout=QVBoxLayout(self); self.table=QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(['Desde','Hasta','Valor','Incluir hasta']); layout.addWidget(self.table)
        row=QHBoxLayout(); layout.addLayout(row)
        for title,callback in [('+ Fila',lambda:self.add([0,1,1,False])),('− Fila',self.remove),('Importar CSV',self.import_csv),('Exportar CSV',self.export_csv)]:
            button=QPushButton(title); button.clicked.connect(callback); row.addWidget(button)
        for rule in rules:self.add(rule)
        self.setMinimumHeight(230)

    def add(self,rule):
        r=self.table.rowCount(); self.table.insertRow(r)
        for c,v in enumerate(rule):self.table.setItem(r,c,QTableWidgetItem(str(v)))

    def remove(self):
        if self.table.currentRow()>=0:self.table.removeRow(self.table.currentRow())

    def value(self):
        out=[]
        for r in range(self.table.rowCount()):
            cells=[self.table.item(r,c).text() if self.table.item(r,c) else '' for c in range(4)]
            out.append([float(cells[0]),float(cells[1]),float(cells[2]),cells[3].strip().lower() in ('true','1','si','sí')])
        return out

    def import_csv(self):
        path,_=QFileDialog.getOpenFileName(self,'Reglas CSV','','CSV (*.csv)')
        if path:
            try:
                with open(path,encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
                self.table.setRowCount(0)
                for r in rows:self.add([float(r['from']),float(r['to']),float(r['value']),r['include_to'].lower() in ('true','1')])
            except Exception as exc:QMessageBox.warning(self,'CSV',str(exc))

    def export_csv(self):
        path,_=QFileDialog.getSaveFileName(self,'Guardar reglas','','CSV (*.csv)')
        if path:
            try:
                with open(path,'w',encoding='utf-8',newline='') as f:
                    w=csv.writer(f); w.writerow(['from','to','value','include_to']); w.writerows(self.value())
            except Exception as exc:QMessageBox.warning(self,'CSV',str(exc))


class NodeDialog(QDialog):
    def __init__(self,node,workflow,sources,parent=None):
        super().__init__(parent); self.node=node; self.workflow=workflow; self.result_node=None; self.preview_requested=False
        algorithm=load_algorithms()[node.algorithm]; self.setWindowTitle(algorithm.title); self.resize(630,720)
        outer=QVBoxLayout(self); title=QLabel(algorithm.title.upper()); title.setObjectName('section'); outer.addWidget(title)
        help_label=QLabel(algorithm.help or 'Configura entradas, parámetros y exportación de este nodo.'); help_label.setWordWrap(True); outer.addWidget(help_label)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); content=QWidget(); form=QFormLayout(content); scroll.setWidget(content); outer.addWidget(scroll)
        self.name=QLineEdit(node.name); form.addRow('Nombre de salida',self.name)
        self.enabled=QCheckBox('Activo'); self.enabled.setChecked(node.enabled); form.addRow('Estado',self.enabled)
        self.ports={}; choices=[(f'{k} · {Path(v).name}',k) for k,v in sources.items()]
        if '$dem' not in sources:choices.insert(0,('$dem · DEM activo','$dem'))
        if '$mask' not in sources:choices.append(('$mask · Máscara del lote','$mask'))
        choices += [(f'{n.name} · {n.id}',n.id) for n in workflow.nodes if n.id!=node.id]
        ports=list(algorithm.ports)
        if node.algorithm=='calculator':ports.append('B')
        for port in ports:
            combo=QComboBox(); combo.addItem('Desconectado',None)
            for label,key in choices:combo.addItem(label,key)
            idx=combo.findData(node.inputs.get(port)); combo.setCurrentIndex(max(0,idx)); self.ports[port]=combo
            form.addRow(f'Entrada {port}',combo)
        self.controls={}
        params=algorithm.defaults|node.parameters
        for key,value in params.items():
            options=CHOICES.get(key)
            if key=='method':options={'smooth':['median','mean','gaussian'],'fill_gaps':['mean','idw'],'slope':['horn','zevenbergen_thorne'],'aspect':['horn','zevenbergen_thorne']}.get(node.algorithm)
            if key=='units':options=['degrees','percent'] if node.algorithm=='slope' else ['cells','m2','ha','km2']
            if key=='unit':options=['pixels','meters','crs'] if node.algorithm in ('tpi','tri','vrm','roughness','local_relief') else ['cells','m2','ha','km2']
            if key=='rules':widget=RulesTable(value)
            elif options:
                widget=QComboBox(); widget.addItems(options); widget.setCurrentText(str(value))
            elif isinstance(value,bool):widget=QCheckBox(); widget.setChecked(value)
            elif isinstance(value,int):widget=QSpinBox(); widget.setRange(-1000000000,1000000000); widget.setValue(value)
            elif isinstance(value,float):widget=QDoubleSpinBox(); widget.setDecimals(8); widget.setRange(-1e12,1e12); widget.setValue(value)
            else:widget=QLineEdit(json.dumps(value) if isinstance(value,list) else str(value))
            self.controls[key]=(widget,value); form.addRow(LABELS.get(key,key),widget)
        self.export=QComboBox()
        for title,key in [('Heredar política global','inherit'),('Temporal','temporary'),('Exportar siempre','always')]:self.export.addItem(title,key)
        self.export.setCurrentIndex(max(0,self.export.findData(node.export))); form.addRow('Exportación',self.export)
        self.dtype=QComboBox(); self.dtype.addItems(['float64','float32','int32']); self.dtype.setCurrentText(node.output_dtype)
        self.nodata=QLineEdit('' if node.output_nodata is None else str(node.output_nodata))
        if algorithm.output=='raster':
            form.addRow('Tipo de salida',self.dtype); form.addRow('NoData salida (vacío = auto)',self.nodata)
        if node.algorithm=='slope':
            note=QLabel('La pendiente porcentual puede superar 100 %. Los DEM geográficos deben reproyectarse.'); note.setWordWrap(True); form.addRow(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        preview=buttons.addButton('Vista previa',QDialogButtonBox.ButtonRole.ActionRole); preview.clicked.connect(self.preview)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); outer.addWidget(buttons)

    def build(self):
        parameters={}
        for key,(w,original) in self.controls.items():
            if isinstance(w,RulesTable):value=w.value()
            elif isinstance(w,QComboBox):value=w.currentText()
            elif isinstance(w,QCheckBox):value=w.isChecked()
            elif isinstance(w,(QSpinBox,QDoubleSpinBox)):value=w.value()
            else:value=json.loads(w.text()) if isinstance(original,list) else w.text()
            parameters[key]=value
        if self.node.algorithm=='calculator':validate_expression(parameters['expression'])
        updated=replace(self.node,name=self.name.text().strip() or self.node.algorithm,
            inputs={k:c.currentData() for k,c in self.ports.items() if c.currentData()},parameters=parameters,
            enabled=self.enabled.isChecked(),export=self.export.currentData())
        updated.output_dtype=self.dtype.currentText(); updated.output_nodata=float(self.nodata.text()) if self.nodata.text() else None
        from dem_tool.core.models import Workflow
        test=Workflow(nodes=[updated if n.id==updated.id else n for n in self.workflow.nodes])
        if not any(n.id==updated.id for n in test.nodes):test.nodes.append(updated)
        test.ordered()
        return updated

    def save(self):
        try:self.result_node=self.build(); self.accept()
        except Exception as exc:QMessageBox.warning(self,'Parámetros',str(exc))

    def preview(self):self.preview_requested=True; self.save()


class StyleDialog(QDialog):
    def __init__(self,layer,parent=None):
        super().__init__(parent); self.setWindowTitle('Simbología · '+layer.name); self.resize(400,350)
        layout=QVBoxLayout(self); form=QFormLayout(); layout.addLayout(form)
        s=layer.style
        self.ramp=QComboBox(); self.ramp.addItems(['terrain','viridis','magma','inferno','grayscale','elevation','blue-red']); self.ramp.setCurrentText(s.ramp); form.addRow('Rampa',self.ramp)
        self.stretch=QComboBox(); self.stretch.addItems(['percentile','minmax','log','equal_interval','quantile','manual']); self.stretch.setCurrentText(s.stretch); form.addRow('Representación',self.stretch)
        self.low=QLineEdit('' if s.minimum is None else str(s.minimum)); self.high=QLineEdit('' if s.maximum is None else str(s.maximum)); form.addRow('Mínimo (vacío = auto)',self.low); form.addRow('Máximo (vacío = auto)',self.high)
        self.alpha=QDoubleSpinBox(); self.alpha.setRange(0,1); self.alpha.setSingleStep(.1); self.alpha.setValue(s.opacity); form.addRow('Opacidad',self.alpha)
        self.classes=QSpinBox(); self.classes.setRange(2,256); self.classes.setValue(s.classes); form.addRow('Clases',self.classes)
        self.breaks=QLineEdit(json.dumps(s.breaks)); form.addRow('Límites manuales (JSON)',self.breaks)
        self.band=QSpinBox(); self.band.setRange(1,1)
        if layer.kind=='raster':
            import rasterio
            with rasterio.open(layer.path) as src:self.band.setMaximum(src.count)
        self.band.setValue(s.band); form.addRow('Banda del raster',self.band)
        note=QLabel('Los cambios solo afectan la representación del mapa.'); note.setWordWrap(True); layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.check); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def check(self):
        try:
            self.result_style=Symbology(self.ramp.currentText(),self.stretch.currentText(),
                float(self.low.text()) if self.low.text() else None,float(self.high.text()) if self.high.text() else None,
                self.alpha.value(),self.classes.value(),json.loads(self.breaks.text()),self.band.value())
            s=self.result_style
            if s.minimum is not None and s.maximum is not None and s.minimum>=s.maximum:raise ValueError('Mínimo debe ser menor que máximo.')
            if s.stretch=='manual' and (len(s.breaks)<2 or any(a>=b for a,b in zip(s.breaks,s.breaks[1:]))):raise ValueError('Límites manuales crecientes, al menos dos.')
            self.accept()
        except Exception as exc:QMessageBox.warning(self,'Simbología',str(exc))
