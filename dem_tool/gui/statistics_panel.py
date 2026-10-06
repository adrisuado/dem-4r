import json
from copy import deepcopy
from PySide6.QtCore import QTimer, QThreadPool
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QSpinBox,QTextBrowser,QHBoxLayout
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from dem_tool.io.raster_io import StatisticsCache
from .preview import BackgroundTask, file_signature


class StatisticsPanel(QWidget):
    def __init__(self):
        super().__init__(); self.cache=StatisticsCache(); self.layer=None; self.last_raster=None
        self._generation=0; self._task=None; self._pending=False; self._key=None
        layout=QVBoxLayout(self); self.title=QLabel('ESTADÍSTICAS / PROPIEDADES'); self.title.setObjectName('section')
        layout.addWidget(self.title); self.sample_note=QLabel(''); self.sample_note.setWordWrap(True); layout.addWidget(self.sample_note)
        self.info=QTextBrowser(); self.info.setMinimumWidth(240); layout.addWidget(self.info,1)
        row=QHBoxLayout(); row.addWidget(QLabel('Intervalos del histograma')); self.bins=QSpinBox(); self.bins.setRange(2,1000); self.bins.setValue(50); row.addWidget(self.bins); layout.addLayout(row)
        self.figure=Figure(figsize=(3,2),facecolor='#172438',layout='constrained'); self.canvas=FigureCanvasQTAgg(self.figure); self.canvas.setMaximumHeight(200); layout.addWidget(self.canvas)
        self.ax=self.figure.add_subplot(111); self.ax.set_facecolor('#172438'); self.ax.tick_params(colors='#bed0df',labelsize=8)
        self.histogram=None
        self.empty_text=self.ax.text(.5,.5,'Sin raster seleccionado',transform=self.ax.transAxes,ha='center',color='#bed0df',fontsize=9)
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self._launch)
        self.bins.valueChanged.connect(lambda:self.show_layer(self.layer))
        self.info.setPlainText('Selecciona una capa para consultar sus propiedades.')

    @property
    def loading(self):
        """Indica si hay estadísticas pendientes o en preparación."""
        return self._task is not None or self.timer.isActive() or self._pending

    def show_layer(self,layer):
        """Deduplica solicitudes y prepara estadísticas sin bloquear la interfaz."""
        self.layer=layer
        try:key=(layer.path,file_signature(layer.path),layer.style.band,self.bins.value(),layer.name,repr(layer.metadata)) if layer else None
        except OSError as exc:self.info.setPlainText(str(exc)); return
        if key==self._key:return
        self._key=key; self._generation+=1; self.timer.stop(); self._pending=layer is not None
        if not layer:
            self.last_raster=None; self.sample_note.setText(''); self.info.setPlainText('No hay un raster visible.')
            if self.histogram:self.histogram.set_visible(False)
            self.empty_text.set_text('Sin raster seleccionado'); self.empty_text.set_visible(True); self.canvas.draw_idle(); return
        self.info.setPlainText(layer.name+' · Calculando propiedades…')
        if self.histogram:self.histogram.set_visible(False)
        self.empty_text.set_text('Calculando…'); self.empty_text.set_visible(True); self.canvas.draw_idle()
        self.timer.start(100)

    def _launch(self):
        """Agrupa cambios de banda, selección y número de intervalos."""
        if self._task is not None or not self._pending:return
        self._pending=False
        layer=deepcopy(self.layer); bins=self.bins.value(); cache=self.cache
        self._task=BackgroundTask(self._generation,lambda:layer_statistics(layer,bins,cache))
        self._task.signals.finished.connect(self._received); QThreadPool.globalInstance().start(self._task)

    def _received(self,generation,result):
        """Actualiza el histograma persistente solo si la selección sigue vigente."""
        self._task=None
        if generation==self._generation:
            if isinstance(result,Exception):
                self.info.setPlainText(str(result)); self.empty_text.set_text('No se pudo leer la capa'); self.sample_note.setText('')
            else:
                stats,histogram=result; layer=self.layer
                if histogram is not None:
                    self.last_raster=layer; counts,edges=histogram
                    self.sample_note.setText(f"Muestra aproximada: {stats['sample_pixels']:,} de {stats['total_pixels']:,} píxeles" if 'valid_sample_pixels' in stats else f"Estadísticas exactas · {stats['total_pixels']:,} píxeles")
                    if self.histogram is None:self.histogram=self.ax.stairs(counts,edges,fill=True,color='#52cfba')
                    else:self.histogram.set_data(values=counts,edges=edges)
                    self.histogram.set_visible(True); self.ax.relim(); self.ax.autoscale_view()
                    self.ax.set_ylabel('Muestra' if 'valid_sample_pixels' in stats else 'Píxeles',color='#bed0df',fontsize=8)
                    self.ax.set_title(layer.name[:26]+('…' if len(layer.name)>26 else ''),color='#bed0df',fontsize=8)
                    self.empty_text.set_text('Sin valores válidos'); self.empty_text.set_visible(not counts.sum())
                else:
                    self.last_raster=None; self.sample_note.setText('Propiedades de la capa seleccionada')
                    if self.histogram:self.histogram.set_visible(False)
                    self.ax.set_title(''); self.empty_text.set_text('Histograma disponible para raster'); self.empty_text.set_visible(True)
                self.info.setPlainText(layer.name+'\n\n'+json.dumps(stats,indent=2,ensure_ascii=False)+'\n\nPROCEDENCIA\n'+json.dumps(layer.metadata,indent=2,ensure_ascii=False))
            self.canvas.draw_idle()
        if self._pending:self.timer.start(0)


def layer_statistics(layer,bins,cache):
    """Lee muestras raster o cabeceras vectoriales fuera del hilo Qt."""
    if layer.kind=='raster':return cache.get(layer.path,bins,layer.style.band)
    if layer.kind=='vector':
        import pyogrio
        info=pyogrio.read_info(layer.path,force_feature_count=True)
        return {'features':int(info['features']),'crs':str(info['crs']),'fields':list(info['fields'])},None
    return layer.metadata,None
