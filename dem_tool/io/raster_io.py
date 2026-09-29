from pathlib import Path
import os
import numpy as np
import rasterio
from pyproj import CRS

VERTICAL_TO_METERS = {'m': 1.0, 'ft': 0.3048, 'us-ft': 1200 / 3937}


def read_raster(path,band=None):
    with rasterio.open(path) as src:
        if src.count != 1 and band is None:
            raise ValueError('Seleccione una banda con el proceso Extraer banda antes de procesar un raster multibanda.')
        limit=int(os.environ.get('DEM_TOOL_MAX_CELLS','25000000'))
        if src.width*src.height>limit:
            raise ValueError(f'Raster de {src.width*src.height:,} celdas; límite de memoria configurado: {limit:,}. Recorte/remuestree externamente o ajuste DEM_TOOL_MAX_CELLS según la RAM disponible.')
        data = src.read(band or 1, masked=True).astype('float64').filled(np.nan)
        data[~np.isfinite(data)] = np.nan
        return data, src.profile.copy()


def write_raster(path, data, profile, tags=None, dtype='float64', nodata=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(profile)
    if dtype not in ('float32','float64','int32'):
        raise ValueError('Tipo de salida: float32, float64 o int32.')
    valid=np.isfinite(data)
    if nodata is None: nodata=np.iinfo('int32').min if dtype=='int32' else np.nan
    if np.isfinite(nodata) and np.any(data[valid]==nodata):
        raise ValueError('El valor NoData coincide con datos válidos; seleccione otro valor.')
    if dtype=='int32':
        if not np.isfinite(nodata) or nodata!=int(nodata) or not np.iinfo('int32').min<=nodata<=np.iinfo('int32').max:
            raise ValueError('NoData debe ser un entero Int32 representable.')
        if np.any(data[valid]!=np.round(data[valid])) or np.any(abs(data[valid])>np.iinfo('int32').max):
            raise ValueError('Int32 perdería valores fraccionarios o excedería su rango; use Float32/64.')
    elif np.any(abs(data[valid])>np.finfo(dtype).max):
        raise ValueError('Valores fuera del rango del tipo de salida.')
    if np.isfinite(nodata):
        if dtype!='int32' and abs(nodata)>np.finfo(dtype).max:
            raise ValueError('NoData fuera del rango del tipo de salida.')
        typed_nodata=np.asarray(nodata).astype(dtype).item()
        if np.any(data[valid].astype(dtype)==typed_nodata):
            raise ValueError('NoData colisiona con datos válidos después de convertir el tipo de salida.')
    profile.update(driver='GTiff', count=1 if data.ndim==2 else data.shape[0], height=data.shape[-2], width=data.shape[-1],
                   dtype=dtype, nodata=nodata, compress='deflate', BIGTIFF='IF_SAFER')
    for key in ('blockxsize', 'blockysize', 'photometric'):
        profile.pop(key, None)
    with rasterio.open(path, 'w', **profile) as dst:
        output=np.where(valid,data,nodata).astype(dtype)
        if data.ndim==2:dst.write(output,1)
        else:dst.write(output)
        dst.write_mask((valid if data.ndim==2 else valid.all(axis=0)).astype('uint8') * 255)
        if tags:
            dst.update_tags(**{k: str(v) for k, v in tags.items()})
    return str(path)


def spatial_info(profile, require_metric=False):
    if not profile.get('crs'):
        raise ValueError('El raster no tiene CRS. Asígnelo solo si conoce el CRS original.')
    crs = CRS(profile['crs'])
    t = profile['transform']
    if require_metric and (not crs.is_projected or not crs.axis_info):
        raise ValueError('Operación métrica: reproyecte el DEM a un CRS proyectado adecuado. Un factor Z no convierte grados en distancias constantes.')
    if require_metric and (abs(t.b) > 1e-10 or abs(t.d) > 1e-10 or t.a <= 0 or t.e >= 0):
        raise ValueError('Reproyecte/rectifique el raster a una cuadrícula orientada al norte.')
    unit = crs.axis_info[0].unit_name if crs.axis_info else 'desconocida'
    factor = crs.axis_info[0].unit_conversion_factor if crs.is_projected else 1.0
    return {'crs': crs.to_string(), 'horizontal_unit': unit, 'resolution': [abs(t.a), abs(t.e)],
            'meters_per_unit': factor, 'dx_m': abs(t.a) * factor, 'dy_m': abs(t.e) * factor}


def align_check(profiles):
    first = profiles[0]
    for other in profiles[1:]:
        if any(first[k] != other[k] for k in ('crs', 'transform', 'width', 'height')):
            raise ValueError('Las entradas deben tener igual CRS, resolución, extensión y alineación; reproyecte primero.')


class StatisticsCache:
    def __init__(self):
        self.values = {}

    def get(self, path, bins=50,band=1):
        path = Path(path)
        s = path.stat()
        key = (str(path), s.st_mtime_ns, s.st_size, int(bins),int(band))
        if key not in self.values:
            a, p = read_raster(path,band)
            v = a[np.isfinite(a)]
            stats = {'valid_pixels': int(v.size), 'nodata_pixels': int(a.size-v.size),
                     'nodata': str(p.get('nodata')), 'width': p['width'], 'height': p['height']}
            try:
                stats.update(spatial_info(p))
            except ValueError:
                stats['crs'] = 'Sin CRS'
            if v.size:
                stats.update(min=float(v.min()), max=float(v.max()), mean=float(v.mean()),
                             median=float(np.median(v)), sd=float(v.std()),
                             percentiles=dict(zip(('p2', 'p25', 'p50', 'p75', 'p98'), map(float, np.percentile(v, [2,25,50,75,98])))))
            self.values[key] = (stats, np.histogram(v, bins=int(bins)))
        return self.values[key]
