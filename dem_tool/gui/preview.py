"""Preparación de vistas en trabajadores; nunca modifica los datos originales."""
from collections import OrderedDict
from contextlib import ExitStack
from pathlib import Path
from threading import RLock

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window, from_bounds, bounds as window_bounds
from PySide6.QtCore import QObject, QRunnable, Signal


class TaskSignals(QObject):
    """Entrega resultados al hilo Qt propietario de la vista."""
    finished = Signal(int, object)


class BackgroundTask(QRunnable):
    """Ejecuta una lectura y devuelve su generación o una excepción."""
    def __init__(self, generation, function):
        super().__init__()
        self.generation = generation
        self.function = function
        self.signals = TaskSignals()

    def run(self):
        try:
            result = self.function()
        except Exception as exc:
            result = exc
        self.signals.finished.emit(self.generation, result)


class PreviewCache:
    """LRU acotada por bytes y entradas, compartida con el trabajador de mapa."""
    def __init__(self, max_bytes=128 * 1024**2, max_entries=48):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.bytes = 0
        self.hits = self.misses = 0
        self.values = OrderedDict()
        self.lock = RLock()

    def get(self, key):
        with self.lock:
            if key not in self.values:
                self.misses += 1
                return None
            self.hits += 1
            self.values.move_to_end(key)
            return self.values[key][0]

    def put(self, key, value):
        size = 4096 + sum(v.nbytes for v in value.values() if isinstance(v, np.ndarray))
        size += sum(a.nbytes for name in ('rings', 'lines') for a in value.get(name, []))
        size += value.get('frame_bytes', 0)
        with self.lock:
            if key in self.values:
                self.bytes -= self.values.pop(key)[1]
            if size <= self.max_bytes:
                self.values[key] = (value, size)
                self.bytes += size
            while self.bytes > self.max_bytes or len(self.values) > self.max_entries:
                self.bytes -= self.values.popitem(last=False)[1][1]

    def retain(self, paths):
        """Libera vistas de capas retiradas del proyecto."""
        with self.lock:
            for key in list(self.values):
                if key[0] not in paths:
                    self.bytes -= self.values.pop(key)[1]


def file_signature(path):
    """Invalida también máscaras externas y componentes de shapefile."""
    path = Path(path)
    files = [path, Path(str(path)+'.msk'), Path(str(path)+'.aux.xml')]
    if path.suffix.lower() == '.shp':
        files = sorted(path.parent.glob(path.stem+'.*'))
    return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files if p.exists())


def raster_preview(path, band, target_crs, extent, size):
    """Lee solo la ventana visible, con muestreo nearest y presupuesto de píxeles."""
    with ExitStack() as stack:
        src = stack.enter_context(rasterio.open(path))
        if src.crs and (src.crs != target_crs or src.transform.b or src.transform.d):
            src = stack.enter_context(WarpedVRT(src, crs=target_crs or src.crs))
        bounds = tuple(src.bounds)
        window = Window(0, 0, src.width, src.height)
        if extent and not (src.transform.b or src.transform.d):
            left, bottom = max(bounds[0], extent[0]), max(bounds[1], extent[1])
            right, top = min(bounds[2], extent[2]), min(bounds[3], extent[3])
            if left >= right or bottom >= top:
                return {'bounds': bounds, 'extent': bounds, 'data': None}
            raw = from_bounds(left, bottom, right, top, src.transform)
            c0, r0 = max(0, int(np.floor(raw.col_off))), max(0, int(np.floor(raw.row_off)))
            c1, r1 = min(src.width, int(np.ceil(raw.col_off+raw.width))), min(src.height, int(np.ceil(raw.row_off+raw.height)))
            window = Window(c0, r0, c1-c0, r1-r0)
        scale = max(1, window.width/size, window.height/size)
        shape = (max(1, int(window.height/scale)), max(1, int(window.width/scale)))
        data = src.read(band, window=window, out_shape=shape, masked=True, out_dtype='float32').filled(np.nan)
        return {'bounds': bounds, 'extent': window_bounds(window, src.transform), 'data': data}


def vector_preview(path, target_crs, extent, size, cache=None):
    """Proyecta y simplifica copias de geometrías para dibujarlas como colecciones."""
    import geopandas as gpd
    key = (path, file_signature(path), str(target_crs), 'vector_source')
    source = cache.get(key) if cache is not None else None
    if source is None:
        frame = gpd.read_file(path, columns=[])
        if target_crs and frame.crs and frame.crs != target_crs:
            frame = frame.to_crs(target_crs)
        frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
        # GEOS memory is not exposed: conservatively account WKB + object overhead.
        weight = int(frame.geometry.to_wkb().str.len().sum())*4 + len(frame)*256
        source = {'frame': frame, 'frame_bytes': weight, 'bounds': tuple(frame.total_bounds) if not frame.empty else None}
        if cache is not None: cache.put(key, source)
    frame = source['frame']
    if frame.empty:
        return {'bounds': None, 'rings': [], 'lines': [], 'points': np.empty((0, 2))}
    bounds = source['bounds']
    if extent:
        frame = frame.iloc[frame.sindex.query(__import__('shapely').box(*extent))]
    b = extent or bounds
    tolerance = max(b[2]-b[0], b[3]-b[1])/size*.25
    rings, lines, points = [], [], []
    pending = list(frame.geometry.simplify(tolerance, preserve_topology=True))
    while pending:
        geom = pending.pop()
        if geom.is_empty:
            continue
        if geom.geom_type == 'Polygon':
            rings.extend(np.asarray(r.coords)[:, :2] for r in [geom.exterior, *geom.interiors])
        elif geom.geom_type in ('LineString', 'LinearRing'):
            lines.append(np.asarray(geom.coords)[:, :2])
        elif geom.geom_type == 'Point':
            points.append((geom.x, geom.y))
        elif hasattr(geom, 'geoms'):
            pending.extend(geom.geoms)
    return {'bounds': bounds, 'rings': rings, 'lines': lines, 'points': np.asarray(points).reshape(-1, 2)}


def prepare_layers(layers, target_crs, extent, size, cache):
    """Construye un lote de vistas sin objetos gráficos ni acceso a widgets."""
    errors, results = [], {}
    if target_crs is None:
        for layer in layers:
            try:
                if layer.kind == 'raster':
                    with rasterio.open(layer.path) as src:
                        target_crs = src.crs
                    if target_crs:
                        break
            except Exception:
                pass
        if target_crs is None:
            for layer in layers:
                if layer.kind == 'vector':
                    try:
                        import pyogrio
                        target_crs = pyogrio.read_info(layer.path)['crs']
                        break
                    except Exception:
                        pass
    raster_size = min(size, max(1, int(np.sqrt(8_000_000/max(1, sum(l.kind == 'raster' for l in layers))))))
    for layer in layers:
        try:
            signature = file_signature(layer.path)
            edge = raster_size if layer.kind == 'raster' else size
            key = (layer.path, signature, str(target_crs), layer.kind, layer.style.band, extent, edge)
            item = cache.get(key)
            if item is None:
                if layer.kind == 'raster':
                    item = raster_preview(layer.path, layer.style.band, target_crs, extent, edge)
                    sample_key = (layer.path, signature, str(target_crs), 'stretch', layer.style.band)
                    sample = cache.get(sample_key)
                    if sample is None:
                        data = raster_preview(layer.path, layer.style.band, target_crs, None, 512)['data']
                        valid = data[np.isfinite(data)]
                        positive = valid[valid > 0]
                        sample = {'quantiles': np.quantile(valid, np.linspace(0, 1, 257)) if valid.size else np.array([]),
                                  'positive_min': float(positive.min()) if positive.size else None}
                        cache.put(sample_key, sample)
                    item = dict(item, **sample)
                else:
                    item = vector_preview(layer.path, target_crs, extent, edge, cache)
                cache.put(key, item)
            results[layer.path] = (key, item)
        except Exception as exc:
            errors.append(f'Visualización de {layer.name}: {exc}')
    return {'crs': target_crs, 'results': results, 'errors': errors}
