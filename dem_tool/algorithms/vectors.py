import numpy as np
import geopandas as gpd
from shapely.geometry import shape
from rasterio.features import shapes
from pyproj import CRS
from .registry import register
from dem_tool.io.raster_io import read_raster
from dem_tool.core.models import Layer


def vector_result(gdf,ctx,name='result',metadata=None):
    ctx.check()
    path=ctx.directory/f'{name}.gpkg'
    gdf.to_file(path,driver='GPKG',layer=name)
    return Layer(str(path),kind='vector',metadata=metadata or {})


@register('polygonize','Poligonizar clases','vectors',{'connectivity':4},output='vector',engine='Rasterio/GDAL')
def polygonize(inputs,p,ctx):
    a,profile=read_raster(inputs['dem'].path)
    valid=np.isfinite(a)
    if not valid.any():
        raise ValueError('No hay píxeles válidos para poligonizar.')
    if p['connectivity'] not in (4,8):
        raise ValueError('Conectividad debe ser 4 u 8.')
    if np.any(a[valid] != np.round(a[valid])) or np.any(abs(a[valid])>2**31-1):
        raise ValueError('Poligonice un raster de clases enteras; reclasifique primero.')
    values=np.where(valid,a,0).astype('int32')
    features=list(shapes(values,mask=valid,transform=profile['transform'],connectivity=p['connectivity']))
    gdf=gpd.GeoDataFrame({'value':[int(v) for _,v in features]},geometry=[shape(g) for g,_ in features],crs=profile['crs'])
    return vector_result(gdf,ctx)


@register('dissolve','Disolver por atributo','vectors',{'field':'value'}, {'vector':'vector'},output='vector',engine='GeoPandas/Shapely')
def dissolve(inputs,p,ctx):
    gdf=gpd.read_file(inputs['vector'].path)
    if p['field'] not in gdf:
        raise ValueError(f"Campo no encontrado: {p['field']}")
    return vector_result(gdf.dissolve(by=p['field'],as_index=False),ctx)


@register('buffer','Buffer métrico','vectors',{'distance_m':100.0},{'vector':'vector'},output='vector',engine='GeoPandas/Shapely')
def buffer(inputs,p,ctx):
    gdf=gpd.read_file(inputs['vector'].path)
    if gdf.crs is None or not CRS(gdf.crs).is_projected:
        raise ValueError('Buffer requiere un CRS proyectado.')
    factor=CRS(gdf.crs).axis_info[0].unit_conversion_factor
    gdf.geometry=gdf.geometry.buffer(p['distance_m']/factor)
    return vector_result(gdf,ctx)
