from copy import deepcopy
import numpy as np
import rasterio
from rasterio.warp import transform as transform_coords
from matplotlib.figure import Figure
from matplotlib.colors import Normalize, LogNorm, BoundaryNorm
from matplotlib.collections import LineCollection
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from PySide6.QtCore import Signal, QTimer, QThreadPool
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QLabel
from .preview import PreviewCache, BackgroundTask, prepare_layers, file_signature


class MapView(QWidget):
    message = Signal(str)
    plotted_raster = Signal(object)
    ready = Signal()

    def __init__(self):
        super().__init__()
        self.figure = Figure(facecolor='#111c2d')
        self.figure.subplots_adjust(left=.065, right=.985, bottom=.09, top=.975)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor('#111c2d')
        self.ax.tick_params(colors='#a9bbcc', labelsize=8)
        for spine in self.ax.spines.values(): spine.set_color('#334258')
        self.ax.set_aspect('equal', adjustable='box')
        self.ax.set_autoscale_on(False)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.framing = QComboBox()
        self.framing.addItem('Llenar vista', 'fill')
        self.framing.addItem('Ver toda la extensión', 'fit')
        self.framing.setToolTip('Llenar conserva proporciones y puede recortar bordes; extensión completa añade un margen.')
        self.toolbar.addWidget(self.framing)
        self.quality = QComboBox()
        for title, edge in [('Rápida', 800), ('Equilibrada', 1400), ('Detalle', 2200)]: self.quality.addItem(title, edge)
        self.quality.setCurrentIndex(1)
        self.quality.setToolTip('Calidad de la vista. No cambia los datos ni los resultados exportados.')
        self.toolbar.addWidget(self.quality)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar); layout.addWidget(self.canvas)
        self.note = QLabel('Añade un DEM o vector para explorar el mapa.'); layout.addWidget(self.note)
        self.layers = []; self.selected = None; self.crs = None; self.bounds = {}
        self.cache = PreviewCache(); self.artists = {}
        self._generation = 0; self._task = None; self._pending = False
        self._preserve = False; self._applying = False; self._framed = False
        self._last_plotted = None; self._last_request = None
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self._launch)
        self.empty_text = self.ax.text(.5, .5, 'DEM / WORKFLOWS', transform=self.ax.transAxes, ha='center', color='#a8cfe0', fontsize=24)
        self.framing.currentIndexChanged.connect(lambda: self.frame_extent())
        self.quality.currentIndexChanged.connect(self.request_view)
        self.canvas.mpl_connect('motion_notify_event', self.coordinates)
        self.canvas.mpl_connect('button_press_event', self.identify)
        self.canvas.mpl_connect('scroll_event', self.scroll)
        self.canvas.mpl_connect('resize_event', self.resize_view)
        self.ax.callbacks.connect('xlim_changed', lambda ax: self.request_view())
        self.ax.callbacks.connect('ylim_changed', lambda ax: self.request_view())

    @property
    def loading(self):
        """Indica si falta preparar o recibir una vista."""
        return self._task is not None or self.timer.isActive() or self._pending

    def reset(self):
        """Descarta el estado visual al cambiar de proyecto sin esperar al disco."""
        self._generation += 1; self.timer.stop(); self._pending = False
        self.crs = None; self.bounds = {}; self._framed = False
        self._last_plotted = None; self._last_request = None
        for record in self.artists.values():
            for artist in record['artists']: artist.remove()
        self.artists.clear(); self.cache.retain(set()); self.layers = []; self.selected = None

    def draw_layers(self, layers, preserve=False):
        """Agrupa cambios, retira artistas obsoletos y solicita una lectura asíncrona."""
        self.layers = list(layers); self._preserve = preserve and self._framed
        paths = {l.path for l in layers}; self.cache.retain(paths)
        visible_paths = {l.path for l in layers if l.visible and l.kind in ('raster', 'vector')}
        for path in list(self.artists):
            if path not in visible_paths:
                for artist in self.artists.pop(path)['artists']: artist.remove()
        self.bounds = {p: b for p, b in self.bounds.items() if p in visible_paths}
        self._generation += 1; self._pending = bool(visible_paths); self._last_request = None
        if visible_paths:
            self.empty_text.set_visible(False); self.timer.start(0)
        else:
            self.timer.stop(); self.empty_text.set_visible(True); self._last_plotted = None
            self.note.setText('No hay capas visibles.'); self.plotted_raster.emit(None)
        self.canvas.draw_idle()

    def request_view(self, *args):
        """Espera 140 ms tras navegar para cargar únicamente el encuadre final."""
        if self._applying or not self._framed or not any(l.visible for l in self.layers): return
        self._preserve = True; self._generation += 1; self._pending = True; self.timer.start(140)

    def resize_view(self, event):
        """Conserva centro y escala vertical al redimensionar el panel."""
        if not self._framed: return
        x, y = self.ax.get_xlim(), self.ax.get_ylim()
        ratio = self.canvas.width()*.92/max(1, self.canvas.height()*.885)
        half = abs(y[1]-y[0])*ratio/2; cx = sum(x)/2
        self._applying = True
        self.ax.set_xlim(cx-half, cx+half)
        self._applying = False; self.request_view()

    def _launch(self):
        """Mantiene como máximo un trabajador y una petición pendiente por mapa."""
        if self._task is not None or not self._pending: return
        layers = deepcopy([l for l in self.layers if l.visible and l.kind in ('raster', 'vector')])
        x, y = sorted(self.ax.get_xlim()), sorted(self.ax.get_ylim())
        extent = tuple(round(v, 10) for v in (x[0], y[0], x[1], y[1])) if self._preserve else None
        size = self.quality.currentData(); crs = self.crs
        request = (tuple((l.path, l.style.band, repr(l.style)) for l in layers), str(crs), extent, size)
        self._pending = False
        if request == self._last_request: return
        self._last_request = request
        cache = self.cache
        self._task = BackgroundTask(self._generation, lambda: prepare_layers(layers, crs, extent, size, cache))
        self._task.signals.finished.connect(self._received)
        self.note.setText('Preparando vista… Puede seguir navegando.')
        QThreadPool.globalInstance().start(self._task)

    def _received(self, generation, result):
        """Descarta respuestas antiguas y aplica solo la solicitud vigente."""
        self._task = None
        self.cache.retain({l.path for l in self.layers})
        if generation == self._generation:
            if isinstance(result, Exception):
                self.message.emit(str(result)); self.note.setText('No se pudo preparar la vista.')
            else: self._apply(result)
        if self._pending: self.timer.start(0)
        self.ready.emit()

    def _normalization(self, item, style):
        """Usa una muestra global estable para evitar cambios de color al navegar."""
        q = item['quantiles']
        if not len(q): return Normalize(0, 1)
        low = style.minimum if style.minimum is not None else float(np.interp(.02, np.linspace(0, 1, len(q)), q) if style.stretch == 'percentile' else q[0])
        high = style.maximum if style.maximum is not None else float(np.interp(.98, np.linspace(0, 1, len(q)), q) if style.stretch == 'percentile' else q[-1])
        high = max(high, low+max(1e-12, abs(low)*1e-12))
        if style.stretch == 'log' and item['positive_min'] is not None:
            low = max(low, item['positive_min']); return LogNorm(low, max(high, low*1.001))
        if style.stretch in ('equal_interval', 'quantile', 'manual'):
            breaks = style.breaks if style.stretch == 'manual' else np.interp(np.linspace(0, 1, style.classes+1), np.linspace(0, 1, len(q)), q) if style.stretch == 'quantile' else np.linspace(low, high, style.classes+1)
            breaks = np.unique(breaks)
            if len(breaks) > 1: return BoundaryNorm(breaks, 256, clip=True)
        return Normalize(low, high)

    def _apply(self, prepared):
        """Actualiza artistas persistentes exclusivamente en el hilo de interfaz."""
        self.crs = prepared['crs']; self.bounds = {}; self._applying = True; last = None
        try:
            for z, layer in enumerate(self.layers, 1):
                if not layer.visible: continue
                result = prepared['results'].get(layer.path)
                if result is None:
                    for artist in self.artists.pop(layer.path, {}).get('artists', []): artist.remove()
                    continue
                key, item = result
                if item['bounds'] is not None: self.bounds[layer.path] = item['bounds']
                record = self.artists.get(layer.path)
                if layer.kind == 'raster':
                    last = layer; data = item['data']
                    if data is None:
                        if record:
                            for artist in record['artists']: artist.set_visible(False)
                        continue
                    b = item['extent']; extent = (b[0], b[2], b[1], b[3])
                    if record is None:
                        artist = self.ax.imshow(np.ma.masked_invalid(data), extent=extent, origin='upper', interpolation='nearest')
                        record = {'artists': [artist], 'key': None, 'style': None}; self.artists[layer.path] = record
                    artist = record['artists'][0]
                    if record['key'] != key:
                        artist.set_data(np.ma.masked_invalid(data)); artist.set_extent(extent)
                    if record['key'] != key or record['style'] != repr(layer.style):
                        artist.set_norm(self._normalization(item, layer.style))
                        artist.set_cmap({'elevation': 'gist_earth', 'blue-red': 'RdBu_r', 'grayscale': 'gray'}.get(layer.style.ramp, layer.style.ramp))
                    artist.set_alpha(layer.style.opacity); artist.set_zorder(z); artist.set_visible(True)
                else:
                    if record is None or record['key'] != key:
                        if record:
                            for artist in record['artists']: artist.remove()
                        artists = []
                        for name, color in [('rings', '#f8cf63'), ('lines', '#57ddf2')]:
                            if item[name]:
                                artist = LineCollection(item[name], colors=color, linewidths=1, zorder=50+z)
                                self.ax.add_collection(artist); artists.append(artist)
                        if len(item['points']):
                            points = item['points']; artists.append(self.ax.scatter(points[:, 0], points[:, 1], s=20, c='#57ddf2', zorder=50+z))
                        record = {'artists': artists}; self.artists[layer.path] = record
                    for artist in record['artists']: artist.set_alpha(layer.style.opacity)
                record['key'] = key; record['style'] = repr(layer.style)
            if self.bounds and not self._preserve: self.frame_extent(last)
        finally:
            self._applying = False
        self.empty_text.set_visible(not self.bounds)
        self.note.setText(f'{len(self.bounds)} capas · Vista {self.quality.currentText().lower()} · Resolución de pantalla')
        for error in prepared['errors']: self.message.emit(error)
        signature = (last.path, last.style.band, file_signature(last.path)) if last else None
        if signature != self._last_plotted:
            self._last_plotted = signature; self.plotted_raster.emit(last)
        self.canvas.draw_idle()

    def full_extent(self, layer=None):
        self.framing.blockSignals(True); self.framing.setCurrentIndex(1); self.framing.blockSignals(False)
        self.frame_extent(layer)

    def frame_extent(self, layer=None):
        values = [self.bounds[layer.path]] if layer and layer.path in self.bounds else list(self.bounds.values())
        if not values: return
        b = np.asarray(values); xmin, ymin = b[:, :2].min(axis=0); xmax, ymax = b[:, 2:].max(axis=0)
        width, height = max(xmax-xmin, 1e-12), max(ymax-ymin, 1e-12)
        ratio = self.canvas.width()*.92/max(1, self.canvas.height()*.885)
        size = max(height, width/ratio)*1.04 if self.framing.currentData() == 'fit' else min(height, width/ratio)
        cx, cy = (xmin+xmax)/2, (ymin+ymax)/2
        previous = self._applying; self._applying = True
        self.ax.set_xlim(cx-size*ratio/2, cx+size*ratio/2); self.ax.set_ylim(cy-size/2, cy+size/2)
        self._framed = True; self._applying = previous; self.canvas.draw_idle()
        if not previous: self.request_view()

    def coordinates(self,event):
        if event.inaxes==self.ax and event.xdata is not None:
            self.message.emit(f'X {event.xdata:,.3f}   Y {event.ydata:,.3f}   |   {self.crs or "CRS no definido"}')

    def identify(self,event):
        if event.inaxes!=self.ax or event.button!=1 or self.toolbar.mode or not self.selected: return
        layer=self.selected
        if layer.kind!='raster': return
        try:
            with rasterio.open(layer.path) as src:
                x,y=event.xdata,event.ydata
                if src.crs and self.crs and src.crs!=self.crs:
                    xx,yy=transform_coords(self.crs,src.crs,[x],[y]); x,y=xx[0],yy[0]
                row,col=src.index(x,y)
                value='Fuera de extensión'
                if 0<=row<src.height and 0<=col<src.width:
                    v=src.read(layer.style.band,window=((row,row+1),(col,col+1)),masked=True)[0,0]
                    value='NoData' if np.ma.is_masked(v) else f'{float(v):.8g}'
                self.message.emit(f'{layer.name}  |  fila {row}, columna {col}  |  valor {value}')
        except Exception as exc: self.message.emit(str(exc))

    def scroll(self,event):
        if event.inaxes!=self.ax:return
        factor=.8 if event.button=='up' else 1.25
        x,y=event.xdata,event.ydata
        self.ax.set_xlim([x+(v-x)*factor for v in self.ax.get_xlim()]); self.ax.set_ylim([y+(v-y)*factor for v in self.ax.get_ylim()])
        self.canvas.draw_idle()
