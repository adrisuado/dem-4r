"""Partición de aportes locales por tramos de una red D8 (no cuencas anidadas)."""
from pathlib import Path
import numpy as np
import geopandas as gpd
from numba import njit
from pyproj import CRS
from .registry import register
from .hydrology import require_direction
from .vectors import vector_result
from dem_tool.io.raster_io import read_raster, spatial_info, align_check


@njit(cache=True)
def drainage_graph(direction):
    """Construye receptores sin wrap/clamp y orden Kahn; rechaza ciclos reales."""
    ny, nx = direction.shape
    n = ny*nx
    receiver = np.full(n, -1, dtype=np.int32)
    incoming = np.zeros(n, dtype=np.int32)
    order = np.empty(n, dtype=np.int32)
    valid_count = 0
    for r in range(ny):
        for c in range(nx):
            code = direction[r, c]
            if not np.isfinite(code):
                continue
            valid_count += 1
            dr, dc = 0, 0
            if code == 1: dc = 1
            elif code == 2: dr, dc = 1, 1
            elif code == 4: dr = 1
            elif code == 8: dr, dc = 1, -1
            elif code == 16: dc = -1
            elif code == 32: dr, dc = -1, -1
            elif code == 64: dr = -1
            elif code == 128: dr, dc = -1, 1
            elif code in (0, -1, -2): continue
            else: raise ValueError('Código D8 no reconocido; utilice la convención ESRI.')
            rr, cc = r+dr, c+dc
            if 0 <= rr < ny and 0 <= cc < nx and np.isfinite(direction[rr, cc]):
                j = rr*nx+cc
                receiver[r*nx+c] = j
                incoming[j] += 1
    end = 0
    for i in range(n):
        if np.isfinite(direction.flat[i]) and incoming[i] == 0:
            order[end] = i
            end += 1
    start = 0
    while start < end:
        i = order[start]; start += 1
        j = receiver[i]
        if j >= 0:
            incoming[j] -= 1
            if incoming[j] == 0:
                order[end] = j; end += 1
    if end != valid_count:
        raise ValueError('La dirección contiene ciclos D8; vuelva a acondicionar y calcular la dirección.')
    return receiver, order[:end]


@njit(cache=True)
def label_stream_links(receiver, order, stream):
    """La confluencia inicia el tramo aguas abajo; cada rama previa conserva su ID."""
    inflow = np.zeros(receiver.size, dtype=np.int32)
    labels = np.zeros(receiver.size, dtype=np.int32)
    for i in order:
        j = receiver[i]
        if stream[i] and j >= 0 and stream[j]: inflow[j] += 1
    count = 0
    for i in order:
        if not stream[i]: continue
        if labels[i] == 0:
            count += 1; labels[i] = count
        j = receiver[i]
        if j >= 0 and stream[j] and inflow[j] == 1:
            labels[j] = labels[i]
    return labels, count


@njit(cache=True)
def assign_local_catchments(receiver, order, seeds):
    """Propaga hacia aguas arriba el ID del primer tramo alcanzado, en O(N)."""
    labels = seeds.copy()
    for k in range(order.size-1, -1, -1):
        i = order[k]
        if labels[i] == 0 and receiver[i] >= 0:
            labels[i] = labels[receiver[i]]
    return labels


@register('stream_links', 'Separar tramos D8', 'hydrology', {},
          {'direction':'raster', 'streams':'raster'}, engine='NumPy/Numba · topología D8',
          help='Identifica tramos entre cabeceras, confluencias y salidas según conexiones D8. La confluencia pertenece al tramo aguas abajo; no agrupa por simple contacto espacial.')
def stream_links(inputs, p, ctx):
    """Produce IDs de tramo y verifica alineación, procedencia y topología."""
    require_direction(inputs['direction'])
    direction, profile = read_raster(inputs['direction'].path)
    streams, sp = read_raster(inputs['streams'].path)
    align_check([profile, sp]); spatial_info(profile, True)
    if inputs['streams'].metadata.get('quantity') != 'stream_mask':
        raise ValueError('Conecte el raster binario de Extraer drenajes.')
    source = inputs['streams'].metadata.get('direction_path')
    if not source or Path(source).resolve() != Path(inputs['direction'].path).resolve():
        raise ValueError('Los drenajes y la dirección deben proceder de la misma rama D8.')
    mask = np.isfinite(streams) & (streams > 0)
    if np.any(mask & ~np.isfinite(direction)):
        raise ValueError('Hay cauces sobre NoData de la dirección.')
    if not mask.any(): raise ValueError('No hay cauces; reduzca el umbral contribuyente o amplíe el DEM.')
    ctx.check(); receiver, order = drainage_graph(direction); ctx.check()
    labels, count = label_stream_links(receiver, order, mask.ravel()); ctx.check()
    out = labels.reshape(direction.shape).astype(float); out[out == 0] = np.nan
    return ctx.raster(out, profile, {'quantity':'stream_links', 'units':'link_id',
        'link_count':int(count), 'direction_path':inputs['direction'].path,
        'junction_policy':'downstream_segment', 'segmentation':'directed_D8'})


@register('subcatchments', 'Delimitar microcuencas por tramo', 'hydrology', {},
          {'direction':'raster', 'links':'raster'}, engine='NumPy/Numba · topología D8',
          help='Asigna cada celda al primer tramo que alcanza siguiendo D8. Genera áreas de aporte local disjuntas, no cuencas completas anidadas. Sin tramo alcanzable queda NoData.')
def subcatchments(inputs, p, ctx):
    """Delimita aportes locales y registra cobertura y celdas no asignadas."""
    require_direction(inputs['direction'])
    direction, profile = read_raster(inputs['direction'].path)
    links, lp = read_raster(inputs['links'].path)
    align_check([profile, lp]); spatial_info(profile, True)
    metadata = inputs['links'].metadata
    if metadata.get('quantity') != 'stream_links' or Path(metadata.get('direction_path','')).resolve() != Path(inputs['direction'].path).resolve():
        raise ValueError('Conecte tramos generados con esta misma dirección D8.')
    valid_links = np.isfinite(links)
    if not valid_links.any() or np.any(valid_links & ~np.isfinite(direction)):
        raise ValueError('Tramos vacíos o situados sobre NoData.')
    values = links[valid_links]
    if np.any(values <= 0) or np.any(values != np.floor(values)) or np.any(values > np.iinfo(np.int32).max):
        raise ValueError('Los IDs de tramo deben ser enteros positivos INT32.')
    seeds = np.where(valid_links, links, 0).astype('int32').ravel()
    ctx.check(); receiver, order = drainage_graph(direction); ctx.check()
    labels = assign_local_catchments(receiver, order, seeds).reshape(direction.shape); ctx.check()
    assigned = int(np.count_nonzero(labels)); valid = int(np.isfinite(direction).sum())
    unassigned = valid-assigned
    if unassigned: ctx.warnings.append(f'{unassigned} celdas válidas no alcanzan un cauce: quedan NoData (salidas, huecos o depresiones).')
    ctx.warnings.append('Los límites del DEM pueden truncar aportes externos; revise el dominio y el margen de recorte.')
    out = labels.astype(float); out[out == 0] = np.nan
    return ctx.raster(out, profile, {'quantity':'local_subcatchments', 'units':'link_id',
        'assigned_cells':assigned, 'unassigned_cells':unassigned, 'valid_cells':valid,
        'assigned_percent':100*assigned/max(1,valid), 'direction_path':inputs['direction'].path,
        'definition':'first_downstream_stream_link', 'nested':False})


@register('finalize_microbasins', 'Preparar microcuencas vectoriales', 'vectors',
          {'field':'value', 'min_area_km2':0.10, 'id_prefix':'MB-'}, {'vector':'vector'},
          optional_ports={'mask':'vector'}, output='vector', engine='GeoPandas/Shapely',
          help='Recorta opcionalmente al AOI, separa partes, calcula AREA_KM2, filtra área mínima y añade MB_ID. Conserva LINK. Las partes recortadas no representan cuencas completas.')
def finalize_microbasins(inputs, p, ctx):
    """Obtiene polígonos finales con área métrica e identidad de tramo preservada."""
    minimum = float(p['min_area_km2'])
    if not np.isfinite(minimum) or minimum < 0: raise ValueError('Área mínima finita y no negativa requerida.')
    if not str(p['id_prefix']).strip(): raise ValueError('Defina un prefijo para MB_ID.')
    frame = gpd.read_file(inputs['vector'].path)
    if frame.empty or not frame.crs or not CRS(frame.crs).is_projected:
        raise ValueError('Se requieren polígonos no vacíos en un CRS proyectado.')
    if p['field'] not in frame: raise ValueError(f"Campo de tramos no encontrado: {p['field']}")
    if not frame.geometry.geom_type.isin(['Polygon','MultiPolygon']).all() or not frame.is_valid.all():
        raise ValueError('Las microcuencas deben ser polígonos válidos.')
    ids = np.asarray(frame[p['field']], dtype=float)
    if not np.isfinite(ids).all() or np.any(ids <= 0) or np.any(ids != np.floor(ids)) or np.any(ids > np.iinfo(np.int32).max):
        raise ValueError('Campo de tramos: se requieren IDs positivos INT32.')
    frame = gpd.GeoDataFrame({'LINK':ids.astype('int32')}, geometry=frame.geometry.values, crs=frame.crs)
    ctx.check()
    if 'mask' in inputs:
        mask = gpd.read_file(inputs['mask'].path)
        if mask.empty or not mask.crs or not mask.is_valid.all() or not mask.geometry.geom_type.isin(['Polygon','MultiPolygon']).all():
            raise ValueError('El AOI debe contener polígonos válidos con CRS.')
        frame = gpd.clip(frame, mask.to_crs(frame.crs), keep_geom_type=True)
        ctx.warnings.append('Salida recortada al AOI: representa partes de áreas de aporte, no cuencas completas.')
    frame = frame.explode(index_parts=False).sort_values('LINK', kind='stable').reset_index(drop=True)
    frame = frame[~frame.geometry.is_empty & frame.geometry.geom_type.eq('Polygon')].copy()
    factor = CRS(frame.crs).axis_info[0].unit_conversion_factor
    frame['AREA_KM2'] = frame.area*factor**2/1e6
    discarded = int((frame.AREA_KM2 < minimum).sum())
    discarded_area = float(frame.loc[frame.AREA_KM2 < minimum,'AREA_KM2'].sum())
    frame = frame[frame.AREA_KM2 >= minimum].reset_index(drop=True)
    if frame.empty: raise ValueError('No quedan microcuencas tras recorte y filtro de área; revise AOI y área mínima.')
    frame['MB_ID'] = [f"{p['id_prefix']}{i+1:05d}" for i in range(len(frame))]
    if discarded: ctx.warnings.append(f'{discarded} partes menores de {minimum:g} km² descartadas; no se fusionan con vecinas.')
    return vector_result(frame[['MB_ID','LINK','AREA_KM2','geometry']], ctx, 'microcuencas',
        {'quantity':'microbasin_polygons', 'count':len(frame), 'area_km2':float(frame.AREA_KM2.sum()),
         'median_area_km2':float(frame.AREA_KM2.median()), 'min_area_km2':minimum,
         'discarded_parts':discarded, 'discarded_area_km2':discarded_area, 'clipped_to_aoi':'mask' in inputs,
         'definition':'local_contributing_areas', 'ids_scope':'current_output'})
