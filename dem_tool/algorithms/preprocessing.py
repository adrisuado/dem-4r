import numpy as np
import geopandas as gpd
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.mask import mask
from rasterio.windows import from_bounds, Window
from scipy import ndimage as ndi
from dem_tool.io.raster_io import read_raster, spatial_info
from .registry import register
from dem_tool.io.spatial import expand_bounds, buffered_vector


@register('select_band','Extraer banda','preprocessing',{'band':1},engine='Rasterio/GDAL',
          help='Selecciona una banda de un raster multibanda para utilizarla como entrada del flujo.')
def select_band(inputs,p,ctx):
    a,profile=read_raster(inputs['dem'].path,int(p['band']))
    return ctx.raster(a,profile,{'source_band':p['band']})


@register('reproject', 'Reproyectar / remuestrear', 'preprocessing',
          {'crs': 'EPSG:32718', 'resolution': 0.0, 'resampling': 'bilinear'}, engine='Rasterio/GDAL')
def warp(inputs, p, ctx):
    a, profile = read_raster(inputs['dem'].path)
    if not profile['crs']:
        raise ValueError('La reproyección requiere conocer el CRS de origen.')
    if p['resampling'] not in ('nearest', 'bilinear', 'cubic', 'average'):
        raise ValueError('Remuestreo no admitido.')
    if p['resolution'] < 0:
        raise ValueError('Resolución debe ser positiva o 0 para automática.')
    with rasterio.open(inputs['dem'].path) as src:
        t, w, h = calculate_default_transform(src.crs, p['crs'], src.width, src.height,
                                               *src.bounds, resolution=p['resolution'] or None)
    if w*h > 100_000_000:
        raise ValueError('La cuadrícula de destino supera 100 millones de celdas; revise resolución/CRS.')
    out = np.full((h, w), np.nan)
    reproject(a, out, src_transform=profile['transform'], src_crs=profile['crs'], src_nodata=np.nan,
              dst_transform=t, dst_crs=p['crs'], dst_nodata=np.nan, resampling=Resampling[p['resampling']])
    profile.update(transform=t, crs=p['crs'], width=w, height=h)
    return ctx.raster(out, profile, inputs['dem'].metadata.copy())


@register('clip', 'Recortar por extensión', 'preprocessing', {'bounds': [], 'bounds_crs':'', 'expand_m':0.0},
          optional_ports={'extent':'vector'}, engine='Rasterio/GDAL',
          help='Conecte un vector en extent o escriba [xmin,ymin,xmax,ymax]. Su CRS se transforma al del DEM. El margen amplía los cuatro lados en metros.')
def clip(inputs, p, ctx):
    with rasterio.open(inputs['dem'].path) as src:
        if not src.crs:raise ValueError('El raster necesita CRS para interpretar la extensión.')
        window = Window(0, 0, src.width, src.height)
        bounds=p['bounds']
        if 'extent' in inputs:
            frame=gpd.read_file(inputs['extent'].path)
            if frame.crs is None or frame.empty:raise ValueError('El vector de extensión está vacío o no tiene CRS.')
            bounds=frame.to_crs(src.crs).total_bounds.tolist()
        elif bounds and p['bounds_crs']:
            from rasterio.warp import transform_bounds
            bounds=list(transform_bounds(p['bounds_crs'],src.crs,*bounds,densify_pts=64))
        if not bounds:bounds=list(src.bounds)
        if bounds:
            if len(bounds) != 4 or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                raise ValueError('Extensión inválida.')
            bounds=expand_bounds(bounds,src.crs,p['expand_m'])
            w = from_bounds(*bounds, transform=src.transform)
            c0, r0 = int(np.floor(w.col_off)), int(np.floor(w.row_off))
            c1, r1 = int(np.ceil(w.col_off+w.width)), int(np.ceil(w.row_off+w.height))
            window = Window(c0, r0, c1-c0, r1-r0).intersection(window)
        a = src.read(1, window=window, masked=True).astype(float).filled(np.nan)
        profile = src.profile.copy()
        profile.update(transform=src.window_transform(window))
    return ctx.raster(a, profile, inputs['dem'].metadata.copy())


@register('clip_mask', 'Recortar por máscara', 'preprocessing', {'buffer_m': 0.0},
          {'dem': 'raster', 'mask': 'vector'}, engine='Rasterio/GDAL + GeoPandas')
def clip_mask(inputs, p, ctx):
    vector = gpd.read_file(inputs['mask'].path)
    if vector.crs is None:
        raise ValueError('La máscara no tiene CRS.')
    with rasterio.open(inputs['dem'].path) as src:
        if not src.crs:
            raise ValueError('El raster no tiene CRS.')
        vector = buffered_vector(vector,p['buffer_m'],src.crs)
        a, t = mask(src, vector.geometry, crop=True, filled=False)
        profile = src.profile.copy()
        profile.update(transform=t)
    return ctx.raster(a[0].astype(float).filled(np.nan), profile, inputs['dem'].metadata.copy())


@register('assign_crs', 'Asignar CRS conocido', 'preprocessing', {'crs': 'EPSG:32718'}, engine='Rasterio/GDAL',
          help='Solo corrige metadatos; no transforma coordenadas. Declare el CRS verdadero.')
def assign_crs(inputs, p, ctx):
    a, profile = read_raster(inputs['dem'].path)
    profile['crs'] = rasterio.crs.CRS.from_user_input(p['crs'])
    return ctx.raster(a, profile, inputs['dem'].metadata.copy())


@register('nodata', 'Asignar NoData', 'preprocessing', {'value': -9999.0})
def nodata(inputs, p, ctx):
    a, profile = read_raster(inputs['dem'].path)
    a[a == p['value']] = np.nan
    return ctx.raster(a, profile, inputs['dem'].metadata.copy())


@register('z_factor', 'Escalar elevaciones', 'preprocessing', {'factor': 1.0, 'output_unit': 'm'})
def scale_z(inputs, p, ctx):
    if p['factor'] <= 0 or p['output_unit'] not in ('m', 'ft', 'us-ft'):
        raise ValueError('Factor Z positivo y unidad vertical m/ft/us-ft requeridos.')
    a, profile = read_raster(inputs['dem'].path)
    return ctx.raster(a * p['factor'], profile, inputs['dem'].metadata | {'vertical_unit': p['output_unit']})


def local_mean(a, footprint):
    valid = np.isfinite(a)
    count = ndi.convolve(valid.astype(float), footprint, mode='constant', cval=0)
    total = ndi.convolve(np.nan_to_num(a), footprint, mode='constant', cval=0)
    return np.divide(total, count, out=np.full_like(a, np.nan), where=count > 0)


@register('fill_gaps', 'Rellenar gaps / NoData', 'preprocessing',
          {'method': 'mean', 'radius': 5, 'iterations': 10, 'max_gap': 100, 'keep_large': True},
          help='Rellena huecos internos; conserva NoData conectado al borde del raster.')
def fill_gaps(inputs, p, ctx):
    a, profile = read_raster(inputs['dem'].path)
    radius, iterations = int(p['radius']), int(p['iterations'])
    if radius < 1 or radius > 100 or iterations < 1 or iterations > 1000 or p['max_gap'] < 1:
        raise ValueError('Radio 1–100, iteraciones 1–1000 y tamaño de gap positivo requeridos.')
    labels, _ = ndi.label(~np.isfinite(a))
    sizes = np.bincount(labels.ravel())
    boundary = np.unique(np.concatenate((labels[0], labels[-1], labels[:,0], labels[:,-1])))
    eligible = (labels > 0) & ~np.isin(labels, boundary)
    if p['keep_large']:
        eligible &= sizes[labels] <= p['max_gap']
    if p['method'] == 'idw':
        from rasterio.fill import fillnodata
        out = fillnodata(np.nan_to_num(a), mask=np.isfinite(a).astype('uint8'), max_search_distance=radius)
        distance = ndi.distance_transform_edt(~np.isfinite(a))
        use = eligible & (distance <= radius)
        a[use] = out[use]
    elif p['method'] == 'mean':
        footprint = np.ones((2*radius+1, 2*radius+1))
        for _ in range(iterations):
            ctx.check()
            need = eligible & ~np.isfinite(a)
            if not need.any():
                break
            avg = local_mean(a, footprint)
            a[need] = avg[need]
    else:
        raise ValueError('Método de gaps: mean o idw.')
    return ctx.raster(a, profile, inputs['dem'].metadata.copy())


@register('smooth', 'Suavizado / filtros', 'preprocessing',
          {'method': 'median', 'kernel': 3, 'iterations': 2, 'sigma': 1.0, 'nodata': 'ignore'})
def smooth(inputs, p, ctx):
    a, profile = read_raster(inputs['dem'].path)
    k, times = int(p['kernel']), int(p['iterations'])
    if k < 3 or k % 2 == 0 or k > 101 or not 1 <= times <= 100 or p['sigma'] <= 0:
        raise ValueError('Kernel impar 3–101, iteraciones 1–100 y sigma positivo requeridos.')
    if p['nodata'] not in ('ignore', 'propagate'):
        raise ValueError('NoData: ignore o propagate.')
    for _ in range(times):
        ctx.check()
        valid = np.isfinite(a)
        if p['method'] == 'mean':
            out = local_mean(a, np.ones((k,k)))
        elif p['method'] == 'median':
            out = ndi.generic_filter(a, lambda v: np.nanmedian(v) if np.isfinite(v).any() else np.nan,
                                     size=k, mode='constant', cval=np.nan)
        elif p['method'] == 'gaussian':
            numerator = ndi.gaussian_filter(np.nan_to_num(a), p['sigma'], radius=k//2, mode='constant')
            denominator = ndi.gaussian_filter(valid.astype(float), p['sigma'], radius=k//2, mode='constant')
            out = np.divide(numerator, denominator, out=np.full_like(a,np.nan), where=denominator>0)
        else:
            raise ValueError('Filtro: mean, median o gaussian.')
        out[~valid] = np.nan
        if p['nodata'] == 'propagate':
            out[ndi.minimum_filter(valid.astype(int), size=k, mode='constant', cval=0) == 0] = np.nan
        a = out
    return ctx.raster(a, profile, inputs['dem'].metadata.copy())
