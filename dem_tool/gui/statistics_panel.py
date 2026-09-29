import json
from pathlib import Path
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QSpinBox,QTextBrowser,QHBoxLayout
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from dem_tool.io.raster_io import StatisticsCache
import geopandas as gpd


class StatisticsPanel(QWidget):
    def __init__(self):
        super().__init__(); self.cache=StatisticsCache(); self.layer=None; self.last_raster=None
        layout=QVBoxLayout(self); self.title=QLabel('ESTADÍSTICAS / PROPIEDADES'); self.title.setObjectName('section')
        layout.addWidget(self.title); self.sample_note=QLabel(''); self.sample_note.setWordWrap(True); layout.addWidget(self.sample_note)
        self.info=QTextBrowser(); self.info.setMinimumWidth(240); layout.addWidget(self.info,1)
        row=QHBoxLayout(); row.addWidget(QLabel('Intervalos del histograma')); self.bins=QSpinBox(); self.bins.setRange(2,1000); self.bins.setValue(50); row.addWidget(self.bins); layout.addLayout(row)
        self.figure=Figure(figsize=(3,2),facecolor='#172438',layout='constrained'); self.canvas=FigureCanvasQTAgg(self.figure); self.canvas.setMaximumHeight(200); layout.addWidget(self.canvas)
        self.bins.valueChanged.connect(lambda:self.show_layer(self.last_raster or self.layer))
        self.info.setPlainText('Selecciona una capa para consultar sus propiedades.')

    def show_layer(self,layer):
        self.layer=layer
        if not layer:
            self.figure.clear(); self.last_raster=None; self.sample_note.setText(''); self.info.setPlainText('No hay un raster visible.'); self.canvas.draw_idle(); return
        try:
            if layer.kind=='raster':
                self.last_raster=layer
                self.figure.clear(); ax=self.figure.add_subplot(111); ax.set_facecolor('#172438'); ax.tick_params(colors='#bed0df',labelsize=8)
                stats,(counts,edges)=self.cache.get(layer.path,self.bins.value(),layer.style.band)
                self.sample_note.setText(f"Muestra aproximada: {stats['sample_pixels']:,} de {stats['total_pixels']:,} píxeles" if 'valid_sample_pixels' in stats else f"Estadísticas exactas · {stats['total_pixels']:,} píxeles")
                ax.stairs(counts,edges,fill=True,color='#52cfba'); ax.set_ylabel('Muestra' if 'valid_sample_pixels' in stats else 'Píxeles',color='#bed0df',fontsize=8)
                ax.set_title(layer.name[:26]+('…' if len(layer.name)>26 else ''),color='#bed0df',fontsize=8)
                if not counts.sum():ax.text(.5,.5,'Sin valores válidos',transform=ax.transAxes,ha='center',color='white')
            elif layer.kind=='vector':
                gdf=gpd.read_file(layer.path); stats={'features':len(gdf),'crs':str(gdf.crs),'fields':list(gdf.columns)}
            else: stats=layer.metadata
            self.info.setPlainText(layer.name+'\n\n'+json.dumps(stats,indent=2,ensure_ascii=False)+'\n\nPROCEDENCIA\n'+json.dumps(layer.metadata,indent=2,ensure_ascii=False))
        except Exception as exc: self.info.setPlainText(str(exc))
        self.canvas.draw_idle()
