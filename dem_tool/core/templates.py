from .models import Workflow,ProcessingNode as Node


def relief_template(crs='EPSG:32718',bounds=None):
    return Workflow(name='Relieve reproducible',nodes=[
        Node('reproject',id='reproject',parameters={'crs':crs}),
        Node('clip',id='clip',inputs={'dem':'reproject'},parameters={'bounds':bounds or []}),
        Node('smooth',id='smooth',inputs={'dem':'clip'},parameters={'iterations':2}),
        Node('slope',id='slope',inputs={'dem':'smooth'}),
        Node('reclassify',id='classes',inputs={'dem':'slope'}),
        Node('polygonize',id='polygons',inputs={'dem':'classes'}),
        Node('dissolve',id='dissolve',inputs={'vector':'polygons'}),
        Node('tpi',id='tpi',inputs={'dem':'smooth'},parameters={'radius':500,'unit':'meters'},name='TPI_500m'),
        Node('curvature',id='curvature',inputs={'dem':'smooth'})])


def hydrology_template():
    return Workflow(name='Hidrología D8',nodes=[
        Node('fill_depressions',id='fill'),
        Node('flow_direction',id='direction',inputs={'dem':'fill'}),
        Node('flow_accumulation',id='accumulation',inputs={'direction':'direction'}),
        Node('streams',id='streams',inputs={'accumulation':'accumulation'})])


def microbasins_template(crs='EPSG:32717',resolution=60.0,threshold_km2=0.45,
                         min_area_km2=0.10,use_aoi=False,margin_m=5000.0):
    """Receta reusable de aportes por tramo; AOI opcional antes/después de hidrología."""
    import math
    from pyproj import CRS
    target=CRS(crs)
    if not target.is_projected or not target.axis_info or abs(target.axis_info[0].unit_conversion_factor-1)>1e-9:
        raise ValueError('Seleccione un CRS proyectado en metros adecuado para el área.')
    if not all(math.isfinite(float(x)) for x in (resolution,threshold_km2,min_area_km2,margin_m)) or resolution<=0 or threshold_km2<=0 or min_area_km2<0 or margin_m<0:
        raise ValueError('Resolución y contribución positivas; área mínima y margen no negativos, todos finitos.')
    nodes=[]
    if use_aoi:
        nodes.append(Node('clip',id='domain',name='Dominio_AOI_con_margen',inputs={'dem':'$dem','extent':'$mask'},parameters={'expand_m':margin_m}))
    nodes.extend([
        Node('reproject',id='dem_metric',name='DEM_metrico',inputs={'dem':'domain' if use_aoi else '$dem'},parameters={'crs':target.to_string(),'resolution':resolution,'resampling':'average'}),
        Node('fill_depressions',id='fill',name='DEM_acondicionado',inputs={'dem':'dem_metric'}),
        Node('flow_direction',id='direction',name='Direccion_D8',inputs={'dem':'fill'}),
        Node('flow_accumulation',id='accumulation',name='Acumulacion_km2',inputs={'direction':'direction'},parameters={'units':'km2'}),
        Node('streams',id='streams',name='Cauces_umbral',inputs={'accumulation':'accumulation'},parameters={'threshold':threshold_km2,'unit':'km2','vector':False,'strahler':False}),
        Node('stream_links',id='links',name='Tramos_D8',inputs={'direction':'direction','streams':'streams'},output_dtype='int32'),
        Node('subcatchments',id='subcatchments',name='Microcuencas_raster',inputs={'direction':'direction','links':'links'},output_dtype='int32'),
        Node('polygonize',id='polygons',name='Microcuencas_poligonos',inputs={'dem':'subcatchments'},parameters={'connectivity':4}),
        Node('dissolve',id='dissolve',name='Microcuencas_por_tramo',inputs={'vector':'polygons'}),
        Node('finalize_microbasins',id='microbasins',name='Microcuencas_finales',inputs={'vector':'dissolve',**({'mask':'$mask'} if use_aoi else {})},parameters={'min_area_km2':min_area_km2})])
    return Workflow(name='Microcuencas por tramos D8',nodes=nodes,export_policy='final')
