import numpy as np
import geopandas as gpd
from shapely.geometry import Point
from pysheds.grid import Grid
from pysheds.sview import Raster, ViewFinder, View
from pyproj import CRS
from .registry import register
from .terrain import metric_dem
from .vectors import vector_result
from dem_tool.io.raster_io import read_raster, spatial_info, align_check, write_raster
from dem_tool.core.models import Layer

DIRMAP=(64,128,1,2,4,8,16,32)


def grid_raster(a,profile,direction=False,pad=False):
    valid=np.isfinite(a)
    nodata=0 if direction else -1.7976931348623157e308
    values=np.where(valid,a,nodata).astype('int64' if direction else 'float64')
    affine=profile['transform']
    if pad:
        from affine import Affine
        values=np.pad(values,1,constant_values=nodata); valid=np.pad(valid,1,constant_values=False)
        affine=affine*Affine.translation(-1,-1)
    vf=ViewFinder(affine=affine,shape=values.shape,nodata=nodata,crs=CRS(profile['crs']),mask=valid)
    r=Raster(values,viewfinder=vf)
    return Grid(viewfinder=vf),r


def require_direction(layer):
    if layer.metadata.get('quantity')!='d8_direction' or layer.metadata.get('dirmap')!=list(DIRMAP):
        raise ValueError('Conecte una dirección D8 generada por este flujo (convención ESRI).')


@register('fill_depressions','Rellenar depresiones','hydrology',
          {'vertical_unit':'inherit','z_factor':1.0,'resolve_flats':True,'epsilon':1e-5,'max_depth':0.0},engine='pysheds',
          help='Priority flood de pysheds; 0 = sin límite de profundidad. Genera diferencia y volumen físico, excluyendo ajuste de planos.')
def fill_depressions(inputs,p,ctx):
    a,profile,info=metric_dem(inputs['dem'],p,ctx)
    if p['epsilon']<=0 or p['max_depth']<0:
        raise ValueError('Epsilon positivo y profundidad máxima no negativa requeridos.')
    grid,dem=grid_raster(a,profile)
    pitless=grid.fill_pits(dem)
    ctx.check()
    filled=grid.fill_depressions(pitless)
    diff=np.asarray(filled).copy()-a
    diff[~np.isfinite(a)]=np.nan
    if p['max_depth'] and np.nanmax(diff)>p['max_depth']:
        raise ValueError('El relleno supera la profundidad máxima. No se genera un DEM parcialmente acondicionado.')
    difference=write_raster(ctx.directory/'fill_difference.tif',diff,profile)
    ctx.check()
    routed=grid.resolve_flats(filled,eps=p['epsilon']) if p['resolve_flats'] else filled
    out=np.asarray(routed).copy(); out[~np.isfinite(a)]=np.nan
    return ctx.raster(out,profile,{'quantity':'conditioned_dem','vertical_unit':'m',
        'filled_volume_m3':float(np.nansum(np.maximum(diff,0))*info['dx_m']*info['dy_m']),
        'max_fill_m':float(np.nanmax(diff)),'artifacts':[difference],
        'flat_adjustment_max_m':float(np.nanmax(out-np.asarray(filled)))})


@register('flow_direction','Dirección de flujo D8','hydrology',{},engine='pysheds')
def flow_direction(inputs,p,ctx):
    a,profile=read_raster(inputs['dem'].path)
    spatial_info(profile,True)
    if inputs['dem'].metadata.get('quantity')!='conditioned_dem':
        ctx.warnings.append('Entrada sin acondicionamiento registrado; pueden quedar depresiones o planos.')
    grid,dem=grid_raster(a,profile)
    direction=grid.flowdir(dem,routing='d8',dirmap=DIRMAP)
    out=np.asarray(direction).astype(float)
    out[~np.isfinite(a)]=np.nan
    unresolved=int(np.count_nonzero((out==-1)|(out==-2)))
    if unresolved:
        ctx.warnings.append(f'{unresolved} celdas planas/deprimidas sin dirección; revise el acondicionamiento.')
    return ctx.raster(out,profile,{'quantity':'d8_direction','dirmap':list(DIRMAP),'units':'ESRI D8','unresolved_cells':unresolved})


@register('flow_accumulation','Acumulación de flujo','hydrology',{'units':'m2'}, {'direction':'raster'},engine='pysheds')
def accumulation(inputs,p,ctx):
    layer=inputs['direction']; require_direction(layer)
    a,profile=read_raster(layer.path); info=spatial_info(profile,True)
    grid,direction=grid_raster(a,profile,True,pad=True)
    acc=np.asarray(grid.accumulation(direction,dirmap=DIRMAP,routing='d8'))[1:-1,1:-1].copy()
    scales={'cells':1,'m2':info['dx_m']*info['dy_m'],'ha':info['dx_m']*info['dy_m']/1e4,'km2':info['dx_m']*info['dy_m']/1e6}
    if p['units'] not in scales: raise ValueError('Unidades: cells, m2, ha o km2.')
    out=acc*scales[p['units']]; out[~np.isfinite(a)]=np.nan
    return ctx.raster(out,profile,{'quantity':'flow_accumulation','units':p['units'],
                                  'includes_self':True,'direction_path':layer.path})


def threshold_mask(layer,p):
    a,profile=read_raster(layer.path); info=spatial_info(profile,True)
    if layer.metadata.get('quantity')!='flow_accumulation':
        raise ValueError('Se requiere una acumulación con unidades registradas.')
    scales={'cells':info['dx_m']*info['dy_m'],'m2':1,'ha':1e4,'km2':1e6}
    unit=layer.metadata['units']
    if p['unit'] not in scales or p['threshold']<=0:
        raise ValueError('Umbral positivo y unidad cells/m2/ha/km2 requeridos.')
    mask=np.isfinite(a)&(a*scales[unit]>=p['threshold']*scales[p['unit']])
    return mask,a,profile


@register('streams','Extraer drenajes','hydrology',{'threshold':1.0,'unit':'km2','vector':True,'strahler':True,'shreve':False},
          {'accumulation':'raster'},engine='pysheds',help='La dirección se recupera de la procedencia de acumulación; genera raster y opcionalmente líneas/Strahler.')
def streams(inputs,p,ctx):
    layer=inputs['accumulation']
    mask,a,profile=threshold_mask(layer,p)
    out=mask.astype(float); out[~np.isfinite(a)]=np.nan
    artifacts=[]
    if mask.any() and (p['vector'] or p['strahler'] or p['shreve']):
        direction_path=layer.metadata.get('direction_path')
        if not direction_path: raise ValueError('No se encontró la dirección asociada a esta acumulación.')
        da,dp=read_raster(direction_path); align_check([profile,dp])
        grid,d=grid_raster(da,dp,True,pad=True)
        stream_mask=Raster(np.pad(mask,1,constant_values=False),viewfinder=d.viewfinder)
        if p['strahler']:
            order=np.asarray(grid.stream_order(d,stream_mask,dirmap=DIRMAP))[1:-1,1:-1].astype(float)
            order[~np.isfinite(a)]=np.nan
            artifacts.append(write_raster(ctx.directory/'strahler.tif',order,profile))
        if p['shreve']:
            magnitude=shreve_array(da,mask,dp)
            magnitude[~np.isfinite(a)]=np.nan
            artifacts.append(write_raster(ctx.directory/'shreve.tif',magnitude,profile))
        if p['vector']:
            network=grid.extract_river_network(d,stream_mask,dirmap=DIRMAP)
            if network['features']:
                gdf=gpd.GeoDataFrame.from_features(network['features'],crs=profile['crs'])
                # pysheds returns pixel corners; shift to cell centres.
                t=profile['transform']
                gdf.geometry=gdf.geometry.translate(xoff=t.a/2,yoff=t.e/2)
                gdf['segment_id']=range(1,len(gdf)+1)
                artifacts.append(vector_result(gdf,ctx,'drainage').path)
    elif not mask.any():
        ctx.warnings.append('Ninguna celda supera el umbral; drenaje raster vacío.')
    return ctx.raster(out,profile,{'quantity':'stream_mask','units':'binary','artifacts':artifacts,
                                  'direction_path':layer.metadata.get('direction_path')})


@register('strahler','Orden de Strahler','hydrology',{}, {'direction':'raster','streams':'raster'},engine='pysheds')
def strahler(inputs,p,ctx):
    require_direction(inputs['direction'])
    da,dp=read_raster(inputs['direction'].path); sa,sp=read_raster(inputs['streams'].path)
    align_check([dp,sp]); grid,d=grid_raster(da,dp,True,pad=True)
    m=Raster(np.pad(np.isfinite(sa)&(sa>0),1,constant_values=False),viewfinder=d.viewfinder)
    out=np.asarray(grid.stream_order(d,m,dirmap=DIRMAP))[1:-1,1:-1].astype(float)
    out[~np.isfinite(da)]=np.nan
    return ctx.raster(out,dp,{'quantity':'strahler_order','units':'order'})


def shreve_array(direction,streams,profile):
    """Route unit weights from stream heads with pysheds accumulation (Shreve)."""
    connected=np.pad(streams,1,constant_values=False)
    codes=np.pad(np.where(np.isfinite(direction),direction,0),1,constant_values=0)
    incoming=np.zeros(connected.shape,dtype=int)
    offsets={1:(0,1),2:(1,1),4:(1,0),8:(1,-1),16:(0,-1),32:(-1,-1),64:(-1,0),128:(-1,1)}
    for code,(dr,dc) in offsets.items():
        incoming+=np.roll(np.roll(connected & (codes==code),dr,axis=0),dc,axis=1)
    heads=connected & (incoming==0)
    grid,d=grid_raster(np.where(streams,direction,0),profile,True,pad=True)
    weights=Raster(heads.astype(float),viewfinder=d.viewfinder)
    out=np.asarray(grid.accumulation(d,weights=weights,dirmap=DIRMAP))[1:-1,1:-1].copy()
    out[~streams]=0
    return out


@register('shreve','Magnitud de Shreve','hydrology',{}, {'direction':'raster','streams':'raster'},engine='pysheds',
          help='Acumulación ponderada de cabeceras: cada cabecera vale 1 y las magnitudes se suman en confluencias.')
def shreve(inputs,p,ctx):
    require_direction(inputs['direction'])
    da,dp=read_raster(inputs['direction'].path); sa,sp=read_raster(inputs['streams'].path)
    align_check([dp,sp]); out=shreve_array(da,np.isfinite(sa)&(sa>0),dp)
    out[~np.isfinite(da)]=np.nan
    return ctx.raster(out,dp,{'quantity':'shreve_magnitude','units':'headwater_count'})


@register('snap_pour_point','Ajustar punto de salida','hydrology',
          {'x':0.0,'y':0.0,'threshold':1.0,'unit':'km2','max_distance_m':1000.0},
          {'accumulation':'raster'},output='vector',engine='pysheds')
def snap_point(inputs,p,ctx):
    mask,a,profile=threshold_mask(inputs['accumulation'],p)
    if not mask.any(): raise ValueError('No hay celdas de drenaje para ajustar el punto.')
    grid,r=grid_raster(a,profile)
    m=Raster(mask,viewfinder=ViewFinder(affine=profile['transform'],shape=a.shape,nodata=False,crs=CRS(profile['crs'])))
    # Work with a centre-based transform when measuring snap distance.
    from affine import Affine
    xy=View.snap_to_mask(mask,(p['x'],p['y']),affine=profile['transform']*Affine.translation(.5,.5))
    info=spatial_info(profile,True)
    distance=float(np.hypot(xy[0]-p['x'],xy[1]-p['y'])*info['meters_per_unit'])
    if p['max_distance_m']<0 or distance>p['max_distance_m']:
        raise ValueError(f'Punto más próximo a {distance:.2f} m; supera la tolerancia.')
    return vector_result(gpd.GeoDataFrame({'distance_m':[distance]},geometry=[Point(*xy)],crs=profile['crs']),ctx)


@register('watershed','Delimitar cuenca','hydrology',{}, {'direction':'raster','point':'vector'},engine='pysheds')
def watershed(inputs,p,ctx):
    require_direction(inputs['direction'])
    a,profile=read_raster(inputs['direction'].path); grid,d=grid_raster(a,profile,True,pad=True)
    points=gpd.read_file(inputs['point'].path)
    if not points.crs or len(points)!=1 or points.geometry.iloc[0].geom_type!='Point':
        raise ValueError('Se requiere un único punto con CRS.')
    point=points.to_crs(profile['crs']).geometry.iloc[0]
    col,row=(~profile['transform'])*(point.x,point.y)
    col,row=int(np.floor(col)),int(np.floor(row))
    if not (0<=row<a.shape[0] and 0<=col<a.shape[1]) or not np.isfinite(a[row,col]):
        raise ValueError('Punto fuera del raster válido.')
    catch=grid.catchment(x=col+1,y=row+1,fdir=d,dirmap=DIRMAP,xytype='index')
    out=np.asarray(catch)[1:-1,1:-1].astype(float); out[~np.isfinite(a)]=np.nan
    return ctx.raster(out,profile,{'quantity':'watershed','outlet':[point.x,point.y], 'units':'binary'})
