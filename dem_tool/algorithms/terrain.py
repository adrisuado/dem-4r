import numpy as np
from scipy import ndimage as ndi
import rasterio
from .registry import register
from .preprocessing import local_mean
from dem_tool.io.raster_io import read_raster, spatial_info, VERTICAL_TO_METERS


def metric_dem(layer, p, ctx):
    a, profile = read_raster(layer.path)
    info = spatial_info(profile, True)
    unit = p.get('vertical_unit', 'inherit')
    if unit == 'inherit':
        unit = layer.metadata.get('vertical_unit', ctx.vertical_unit)
    if unit not in VERTICAL_TO_METERS or p.get('z_factor', 1) <= 0:
        raise ValueError('Declare unidad vertical válida y factor Z positivo.')
    return a * VERTICAL_TO_METERS[unit] * p.get('z_factor', 1), profile, info


def derivatives(a, info, method='horn', edges='nodata'):
    dx, dy = info['dx_m'], info['dy_m']
    if edges not in ('nodata', 'local'):
        raise ValueError('Bordes: nodata o local.')
    valid = np.isfinite(a)
    mode = 'nearest' if edges == 'local' else 'constant'
    filled = np.where(valid, a, 0)
    if method == 'horn':
        gx = ndi.correlate(filled, np.array([[-1,0,1],[-2,0,2],[-1,0,1]]) / (8*dx), mode=mode)
        gy = ndi.correlate(filled, np.array([[1,2,1],[0,0,0],[-1,-2,-1]]) / (8*dy), mode=mode)
    elif method == 'zevenbergen_thorne':
        gx = ndi.correlate(filled, np.array([[0,0,0],[-1,0,1],[0,0,0]]) / (2*dx), mode=mode)
        gy = ndi.correlate(filled, np.array([[0,1,0],[0,0,0],[0,-1,0]]) / (2*dy), mode=mode)
    else:
        raise ValueError('Método: horn o zevenbergen_thorne.')
    keep = ndi.minimum_filter(valid.astype(int), size=3, mode=mode, cval=0).astype(bool)
    gx[~keep] = gy[~keep] = np.nan
    return gx, gy, keep


COMMON = {'vertical_unit': 'inherit', 'z_factor': 1.0, 'edges': 'nodata'}


@register('slope', 'Pendiente', 'relief', COMMON | {'method': 'horn', 'units': 'degrees'},
          help='Pendiente Horn o Zevenbergen–Thorne; porcentaje puede superar 100 %.')
def slope(inputs, p, ctx):
    a, profile, info = metric_dem(inputs['dem'], p, ctx)
    gx, gy, _ = derivatives(a, info, p['method'], p['edges'])
    gradient = np.hypot(gx, gy)
    if p['units'] == 'degrees':
        out = np.degrees(np.arctan(gradient))
    elif p['units'] == 'percent':
        out = 100*gradient
        ctx.warnings.append('Pendiente porcentual puede superar 100 %.')
    else:
        raise ValueError('Unidad de pendiente: degrees o percent.')
    return ctx.raster(out, profile, {'units': p['units'], 'method': p['method']})


@register('aspect', 'Orientación / aspect', 'relief', COMMON | {'method': 'horn'})
def aspect(inputs, p, ctx):
    a, profile, info = metric_dem(inputs['dem'], p, ctx)
    gx, gy, _ = derivatives(a, info, p['method'], p['edges'])
    out = np.degrees(np.arctan2(-gx, -gy)) % 360
    out[np.hypot(gx,gy) < 1e-12] = np.nan
    return ctx.raster(out, profile, {'units': 'degrees clockwise from north', 'flat': 'NoData'})


@register('hillshade', 'Relieve sombreado', 'relief', COMMON | {'azimuth': 315.0, 'altitude': 45.0})
def hillshade(inputs, p, ctx):
    if not 0 <= p['altitude'] <= 90:
        raise ValueError('Altitud solar entre 0 y 90 grados.')
    a, profile, info = metric_dem(inputs['dem'], p, ctx)
    gx, gy, _ = derivatives(a, info, edges=p['edges'])
    az, alt = np.radians(p['azimuth']), np.radians(p['altitude'])
    out = (-gx*np.cos(alt)*np.sin(az)-gy*np.cos(alt)*np.cos(az)+np.sin(alt))/np.sqrt(1+gx**2+gy**2)
    return ctx.raster(255*np.clip(out,0,1), profile, {'units': '0-255'})


@register('curvature', 'Curvatura', 'relief', COMMON | {'kind': 'general'},
          help='Diferencias centrales Zevenbergen–Thorne. General = -(zxx+zyy); perfil y planta según fórmulas documentadas.')
def curvature(inputs, p, ctx):
    a, profile, info = metric_dem(inputs['dem'], p, ctx)
    gx, gy, keep = derivatives(a, info, 'zevenbergen_thorne', p['edges'])
    dx, dy = info['dx_m'], info['dy_m']
    mode = 'nearest' if p['edges'] == 'local' else 'constant'
    r = ndi.correlate(a, np.array([[0,0,0],[1,-2,1],[0,0,0]])/dx**2, mode=mode)
    t = ndi.correlate(a, np.array([[0,1,0],[0,-2,0],[0,1,0]])/dy**2, mode=mode)
    s = ndi.correlate(a, np.array([[-1,0,1],[0,0,0],[1,0,-1]])/(4*dx*dy), mode=mode)
    q = gx**2 + gy**2
    if p['kind'] == 'general':
        out = -(r+t)
    elif p['kind'] in ('profile', 'plan', 'tangential'):
        if p['kind'] == 'profile':
            num, den = -(r*gx**2+2*s*gx*gy+t*gy**2), q*(1+q)**1.5
        else:
            num = -(r*gy**2-2*s*gx*gy+t*gx**2)
            den = q**1.5 if p['kind'] == 'plan' else q*np.sqrt(1+q)
        out = np.divide(num, den, out=np.zeros_like(a), where=den>1e-15)
    else:
        raise ValueError('Curvatura: general, profile, plan o tangential.')
    out[~keep] = np.nan
    return ctx.raster(out, profile, {'units': '1/m', 'kind': p['kind'], 'method': 'Zevenbergen-Thorne central differences'})


@register('curvatures','Conjunto de curvaturas','relief',COMMON|{'products':['general','profile','plan'],'packaging':'both'},
          help='Productos general/profile/plan/tangential. Salidas separate, multiband o both. Para encadenar una banda use Extraer banda.')
def curvature_bundle(inputs,p,ctx):
    from dataclasses import replace
    from pathlib import Path
    if p['packaging'] not in ('separate','multiband','both') or not p['products']:
        raise ValueError('Indique productos y empaquetado separate/multiband/both.')
    arrays=[]; files=[]
    for kind in dict.fromkeys(p['products']):
        if kind not in ('general','profile','plan','tangential'):raise ValueError('Tipo de curvatura desconocido.')
        subdir=ctx.directory/kind; subdir.mkdir(exist_ok=True)
        result=curvature(inputs,{k:v for k,v in p.items() if k in COMMON}|{'kind':kind},replace(ctx,directory=subdir))
        a,profile=read_raster(result.path); arrays.append(a)
        target=ctx.directory/f'curv_{kind}.tif'; Path(result.path).replace(target); subdir.rmdir(); files.append(str(target))
    metadata={'units':'1/m','bands':list(dict.fromkeys(p['products']))}
    if p['packaging']=='separate':
        from dem_tool.core.models import Layer
        return Layer(files[0],metadata=metadata|{'artifacts':files[1:]})
    result=ctx.raster(np.stack(arrays),profile,metadata)
    with rasterio.open(result.path,'r+') as dst:
        for band,name in enumerate(metadata['bands'],1):dst.set_band_description(band,name)
    if p['packaging']=='both':result.metadata['artifacts']=files
    else:
        for f in files:Path(f).unlink()
    return result


def footprint(profile, radius, unit, shape):
    if radius <= 0 or not np.isfinite(radius):
        raise ValueError('Radio positivo requerido.')
    if unit == 'pixels':
        rx = ry = float(radius)
    else:
        info = spatial_info(profile, True)
        scale = info['meters_per_unit'] if unit == 'crs' else 1
        if unit not in ('meters', 'crs'):
            raise ValueError('Unidad de radio: pixels, meters o crs.')
        rx, ry = radius*scale/info['dx_m'], radius*scale/info['dy_m']
    nx, ny = int(np.ceil(rx)), int(np.ceil(ry))
    if (2*nx+1)*(2*ny+1) > 1_000_000:
        raise ValueError('Vecindad excesiva (>1 millón de celdas). Reduzca radio o remuestree.')
    yy, xx = np.mgrid[-ny:ny+1, -nx:nx+1]
    if shape == 'circle':
        f = (xx/rx)**2+(yy/ry)**2 <= 1+1e-12
    elif shape == 'square':
        f = (abs(xx)<=rx)&(abs(yy)<=ry)
    else:
        raise ValueError('Forma: circle o square.')
    if f.sum() < 2:
        raise ValueError('El radio no incluye vecinos; aumente la escala.')
    return f


NEIGHBOR = {'radius': 1.0, 'unit': 'pixels', 'shape': 'square', 'vertical_unit': 'inherit', 'z_factor': 1.0}


@register('tpi', 'TPI — posición topográfica', 'relief', NEIGHBOR | {'standardize': False},
          help='Elevación central menos media de vecinos excluyendo el centro. Estandarización por SD local.')
def tpi(inputs, p, ctx):
    a, profile, _ = metric_dem(inputs['dem'], p, ctx)
    f = footprint(profile, p['radius'], p['unit'], p['shape']).astype(float)
    f[f.shape[0]//2, f.shape[1]//2] = 0
    avg = local_mean(a, f)
    out = a-avg
    if p['standardize']:
        sd = np.sqrt(np.maximum(local_mean(a*a,f)-avg*avg, 0))
        out = np.divide(out, sd, out=np.full_like(a,np.nan), where=sd>1e-12)
    return ctx.raster(out, profile, {'units': 'dimensionless' if p['standardize'] else 'm'})


@register('tri', 'TRI — Riley', 'relief', NEIGHBOR,
          help='Raíz de la suma de diferencias cuadráticas con vecinos válidos; no es RMS.')
def tri(inputs, p, ctx):
    a, profile, _ = metric_dem(inputs['dem'], p, ctx)
    f = footprint(profile, p['radius'], p['unit'], p['shape']).astype(float)
    f[f.shape[0]//2,f.shape[1]//2] = 0
    valid = np.isfinite(a)
    n = ndi.convolve(valid.astype(float),f,mode='constant')
    s = ndi.convolve(np.nan_to_num(a),f,mode='constant')
    s2 = ndi.convolve(np.nan_to_num(a*a),f,mode='constant')
    out = np.sqrt(np.maximum(s2-2*a*s+n*a*a,0))
    out[(n==0)|~valid] = np.nan
    return ctx.raster(out,profile,{'units':'m','method':'Riley sum squared differences'})


def range_relief(inputs,p,ctx):
    a,profile,_ = metric_dem(inputs['dem'],p,ctx)
    f=footprint(profile,p['radius'],p['unit'],p['shape'])
    high=ndi.maximum_filter(np.where(np.isfinite(a),a,-np.inf),footprint=f,mode='constant',cval=-np.inf)
    low=ndi.minimum_filter(np.where(np.isfinite(a),a,np.inf),footprint=f,mode='constant',cval=np.inf)
    out=high-low
    out[~np.isfinite(a)]=np.nan
    return ctx.raster(out,profile,{'units':'m','definition':'local maximum minus minimum'})


register('roughness','Rugosidad (rango local)','relief',NEIGHBOR)(range_relief)
register('local_relief','Relieve local','relief',NEIGHBOR)(range_relief)


@register('vrm','VRM — rugosidad vectorial','relief',NEIGHBOR)
def vrm(inputs,p,ctx):
    a,profile,info=metric_dem(inputs['dem'],p,ctx)
    gx,gy,_=derivatives(a,info)
    f=footprint(profile,p['radius'],p['unit'],p['shape']).astype(float)
    norm=np.sqrt(1+gx*gx+gy*gy)
    out=1-np.sqrt(local_mean(-gx/norm,f)**2+local_mean(-gy/norm,f)**2+local_mean(1/norm,f)**2)
    out[~np.isfinite(norm)]=np.nan
    return ctx.raster(np.clip(out,0,1),profile,{'units':'dimensionless'})
