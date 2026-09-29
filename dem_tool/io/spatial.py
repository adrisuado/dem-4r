"""Local metric expansion without treating angular degrees as fixed distances."""
import numpy as np
import geopandas as gpd
from pyproj import CRS, Transformer
from rasterio.warp import transform_bounds


def local_metric_crs(bounds, crs):
    west,south,east,north=map(float,bounds)
    lon,lat=Transformer.from_crs(crs,4326,always_xy=True).transform((west+east)/2,(south+north)/2)
    if not np.isfinite([lon,lat]).all() or not -90<lat<90:
        raise ValueError('No se pudo determinar un CRS métrico local para esta extensión.')
    return CRS.from_proj4(f'+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs')


def expand_bounds(bounds, crs, meters):
    crs=CRS.from_user_input(crs)
    bounds=tuple(map(float,bounds)); meters=float(meters)
    if not np.isfinite([*bounds,meters]).all() or meters<0:
        raise ValueError('Extensión finita y margen no negativo requeridos.')
    if not meters:return bounds
    if crs.is_projected:
        delta=meters/crs.axis_info[0].unit_conversion_factor
        return (bounds[0]-delta,bounds[1]-delta,bounds[2]+delta,bounds[3]+delta)
    if not crs.is_geographic:raise ValueError('Se requiere un CRS geográfico o proyectado.')
    if bounds[2]-bounds[0]>30 or bounds[3]-bounds[1]>30:
        raise ValueError('La expansión métrica local requiere una extensión menor a 30° por eje; divida el área.')
    metric=local_metric_crs(bounds,crs)
    b=transform_bounds(crs,metric,*bounds,densify_pts=64)
    extended=(b[0]-meters,b[1]-meters,b[2]+meters,b[3]+meters)
    return transform_bounds(metric,crs,*extended,densify_pts=64)


def buffered_vector(frame, meters, target_crs):
    if frame.crs is None:raise ValueError('El vector no tiene CRS.')
    if frame.empty or frame.geometry.is_empty.all():raise ValueError('Vector vacío.')
    meters=float(meters)
    if not np.isfinite(meters):raise ValueError('Buffer debe ser finito.')
    projected=frame.to_crs(target_crs)
    crs=CRS.from_user_input(target_crs)
    if meters:
        if crs.is_projected:
            projected.geometry=projected.buffer(meters/crs.axis_info[0].unit_conversion_factor)
        else:
            bounds=projected.total_bounds
            if bounds[2]-bounds[0]>30 or bounds[3]-bounds[1]>30:
                raise ValueError('Buffer métrico local: divida áreas mayores a 30° por eje.')
            metric=local_metric_crs(bounds,crs)
            projected=projected.to_crs(metric)
            projected.geometry=projected.buffer(meters)
            projected=projected.to_crs(target_crs)
    if projected.geometry.is_empty.all():raise ValueError('El buffer elimina toda la máscara.')
    return projected
