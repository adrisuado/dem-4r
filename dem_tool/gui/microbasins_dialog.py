"""Configuración inicial de la plantilla; las rutas continúan siendo variables del proyecto."""
from pathlib import Path
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLabel,QLineEdit,
    QDoubleSpinBox,QCheckBox,QPushButton,QFileDialog,QDialogButtonBox,QMessageBox)
from dem_tool.core.templates import microbasins_template


def suggest_metric_crs(path):
    """Sugiere CRS métrico existente o zona UTM del centro, sin imponerlo."""
    if path:
        try:
            import rasterio
            from pyproj import CRS,Transformer
            with rasterio.open(path) as src:
                crs=CRS(src.crs)
                if crs.is_projected and abs(crs.axis_info[0].unit_conversion_factor-1)<1e-9:return crs.to_string()
                lon,lat=Transformer.from_crs(crs,4326,always_xy=True).transform((src.bounds.left+src.bounds.right)/2,(src.bounds.bottom+src.bounds.top)/2)
                if -80<=lat<=84 and -180<=lon<=180:
                    zone=min(60,max(1,int((lon+180)//6)+1))
                    return f'EPSG:{(32600 if lat>=0 else 32700)+zone}'
        except Exception:pass
    return 'EPSG:32717'


class MicrobasinsDialog(QDialog):
    """Permite escoger DEM/AOI y parámetros principales antes de reemplazar el flujo."""
    def __init__(self,sources,parent=None):
        super().__init__(parent); self.setWindowTitle('Plantilla · Microcuencas por tramos D8'); self.resize(650,560)
        self.result_workflow=None; self.result_sources={}
        layout=QVBoxLayout(self); form=QFormLayout(); layout.addLayout(form)
        note=QLabel('Áreas de aporte local de cada tramo de cauce. No necesita puntos de salida. Revise el CRS sugerido: debe ser proyectado en metros y adecuado para toda el área.'); note.setWordWrap(True); form.addRow(note)
        self.dem=QLineEdit(sources.get('$dem','')); form.addRow('DEM de entrada',self.dem)
        button=QPushButton('Elegir DEM…'); button.clicked.connect(self.choose_dem); form.addRow(button)
        self.crs=QLineEdit(suggest_metric_crs(self.dem.text())); form.addRow('CRS de trabajo',self.crs)
        self.resolution=QDoubleSpinBox(); self.resolution.setRange(.001,100000); self.resolution.setDecimals(3); self.resolution.setValue(60); form.addRow('Resolución de enrutamiento (m)',self.resolution)
        self.threshold=QDoubleSpinBox(); self.threshold.setDecimals(6); self.threshold.setRange(.000001,1e8); self.threshold.setValue(.45); form.addRow('Contribución mínima para cauces (km²)',self.threshold)
        self.minimum=QDoubleSpinBox(); self.minimum.setDecimals(6); self.minimum.setRange(0,1e8); self.minimum.setValue(.10); form.addRow('Área mínima por polígono final (km²)',self.minimum)
        self.use_aoi=QCheckBox('Usar AOI: recortar dominio y polígonos finales'); self.use_aoi.setChecked(bool(sources.get('$mask'))); form.addRow(self.use_aoi)
        self.mask=QLineEdit(sources.get('$mask','')); form.addRow('AOI poligonal',self.mask)
        self.browse_mask=QPushButton('Elegir AOI…'); self.browse_mask.clicked.connect(self.choose_mask); form.addRow(self.browse_mask)
        self.margin=QDoubleSpinBox(); self.margin.setRange(0,1000000); self.margin.setValue(5000); form.addRow('Margen del dominio alrededor del AOI (m)',self.margin)
        self.use_aoi.toggled.connect(self.toggle_aoi); self.toggle_aoi(self.use_aoi.isChecked())
        warning=QLabel('60 m y 0,45 km² equivalen a 125 celdas cuadradas. El margen no garantiza captar todos los aportes externos. Las partes menores del área mínima se descartan, no se fusionan. Sin AOI se procesa el DEM completo.'); warning.setWordWrap(True); form.addRow(warning)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def toggle_aoi(self,enabled):
        """Habilita los controles que dependen del área de interés."""
        for widget in (self.mask,self.browse_mask,self.margin):widget.setEnabled(enabled)

    def choose_dem(self):
        """Selecciona un raster y actualiza la sugerencia de CRS."""
        path,_=QFileDialog.getOpenFileName(self,'DEM de entrada','','Raster (*.tif *.tiff *.img *.asc)')
        if path:self.dem.setText(path); self.crs.setText(suggest_metric_crs(path))

    def choose_mask(self):
        """Selecciona el archivo del AOI sin fijar rutas dentro de la receta."""
        path,_=QFileDialog.getOpenFileName(self,'AOI poligonal','','Vector (*.gpkg *.shp *.geojson)')
        if path:self.mask.setText(path)

    def build(self):
        """Valida insumos y construye una receta aislada de la sesión activa."""
        import rasterio
        import geopandas as gpd
        path=Path(self.dem.text().strip()).resolve()
        with rasterio.open(path) as src:
            if src.count!=1 or not src.crs:raise ValueError('El DEM debe tener una banda y CRS conocido.')
        sources={'$dem':str(path)}
        if self.use_aoi.isChecked():
            mask=Path(self.mask.text().strip()).resolve(); frame=gpd.read_file(mask)
            if frame.empty or not frame.crs or not frame.is_valid.all() or not frame.geometry.geom_type.isin(['Polygon','MultiPolygon']).all():
                raise ValueError('El AOI debe contener polígonos válidos con CRS.')
            sources['$mask']=str(mask)
        workflow=microbasins_template(self.crs.text(),self.resolution.value(),self.threshold.value(),self.minimum.value(),self.use_aoi.isChecked(),self.margin.value())
        return workflow,sources

    def save(self):
        """Acepta solo configuraciones válidas; los errores mantienen abierto el diálogo."""
        try:self.result_workflow,self.result_sources=self.build(); self.accept()
        except Exception as exc:QMessageBox.warning(self,'Plantilla de microcuencas',str(exc))
