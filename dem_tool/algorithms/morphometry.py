import math
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape, LineString
from shapely.ops import unary_union
from rasterio.features import shapes
from pysheds.sview import Raster
from .registry import register
from .terrain import metric_dem, derivatives
from .hydrology import grid_raster, require_direction, DIRMAP
from dem_tool.io.raster_io import read_raster, align_check
from dem_tool.core.models import Layer


@register('morphometry','Morfometría de cuenca','tables',{'vertical_unit':'inherit','z_factor':1.0},
          {'dem':'raster','basin':'raster','direction':'raster','streams':'raster','order':'raster'},
          output='table',engine='pysheds + GeoPandas/Shapely',
          help='Cuenca binaria, dirección D8, drenajes y Strahler alineados. Exporta CSV, XLSX y GeoPackage.')
def morphometry(inputs,p,ctx):
    z,profile,info=metric_dem(inputs['dem'],p,ctx)
    basin,bp=read_raster(inputs['basin'].path)
    da,dp=read_raster(inputs['direction'].path)
    streams,sp=read_raster(inputs['streams'].path)
    order,op=read_raster(inputs['order'].path)
    align_check([profile,bp,dp,sp,op]); require_direction(inputs['direction'])
    inside=np.isfinite(basin)&(basin>0)&np.isfinite(z)
    if not inside.any(): raise ValueError('Cuenca vacía.')
    polygons=[shape(g) for g,v in shapes(inside.astype('uint8'),mask=inside,transform=profile['transform']) if v==1]
    geom=unary_union(polygons)
    factor=info['meters_per_unit']; area=geom.area*factor**2; perimeter=geom.length*factor
    values=z[inside]; low,high,mean=map(float,(values.min(),values.max(),values.mean()))
    gx,gy,_=derivatives(z,info)
    slope=np.degrees(np.arctan(np.hypot(gx,gy)))
    valid_slopes=slope[inside & np.isfinite(slope)]
    grid,direction=grid_raster(da,dp,True,pad=True)
    outlet=inputs['basin'].metadata.get('outlet')
    if not outlet: raise ValueError('La cuenca debe incluir un punto de salida registrado por Watershed.')
    t=profile['transform']; col,row=(~t)*tuple(outlet); col,row=int(np.floor(col)),int(np.floor(row))
    offsets={1:(0,1),2:(1,1),4:(1,0),8:(1,-1),16:(0,-1),32:(-1,-1),64:(-1,0),128:(-1,1)}
    weights=np.zeros_like(da)
    for code,(dr,dc) in offsets.items():
        weights[da==code]=np.hypot(dr*info['dy_m'],dc*info['dx_m'])
    wr=Raster(np.pad(weights,1,constant_values=0),viewfinder=direction.viewfinder)
    distance=np.asarray(grid.distance_to_outlet(col+1,row+1,direction,weights=wr,dirmap=DIRMAP,xytype='index'))[1:-1,1:-1]
    channel=inside & np.isfinite(streams)&(streams>0)&np.isfinite(distance)
    main_geometry=None; main_length=None; channel_slope=None
    if channel.any():
        start=np.unravel_index(np.argmax(np.where(channel,distance,-np.inf)),z.shape)
        rr,cc=start; coordinates=[]; seen=set()
        while (rr,cc) not in seen and 0<=rr<z.shape[0] and 0<=cc<z.shape[1] and inside[rr,cc]:
            seen.add((rr,cc)); coordinates.append(t*(cc+.5,rr+.5))
            if (rr,cc)==(row,col): break
            offset=offsets.get(int(da[rr,cc]))
            if not offset: break
            rr,cc=rr+offset[0],cc+offset[1]
        if len(coordinates)>1 and (rr,cc)==(row,col):
            main_geometry=LineString(coordinates)
            main_length=main_geometry.length*factor
            channel_slope=float((z[start]-z[row,col])/main_length) if main_length else None
    mask=Raster(np.pad(inside & np.isfinite(streams)&(streams>0),1,constant_values=False),viewfinder=direction.viewfinder)
    mask.viewfinder.nodata=False
    net=grid.extract_river_network(direction,mask,dirmap=DIRMAP)
    lengths=[]
    if net['features']:
        network=gpd.GeoDataFrame.from_features(net['features'],crs=profile['crs'])
        network.geometry=network.geometry.translate(xoff=t.a/2,yoff=t.e/2).intersection(geom)
        lengths=[float(g.length*factor) for g in network.geometry if not g.is_empty and g.length>0]
    hull=np.asarray(geom.convex_hull.exterior.coords)
    basin_length=float(np.max(np.hypot(hull[:,0]-outlet[0],hull[:,1]-outlet[1]))*factor)
    vals=order[inside&np.isfinite(order)&(order>0)]
    metrics={'area_m2':area,'area_km2':area/1e6,'perimeter_m':perimeter,
        'elevation_min_m':low,'elevation_max_m':high,'elevation_mean_m':mean,'relief_m':high-low,
        'slope_mean_degrees':float(valid_slopes.mean()) if valid_slopes.size else None,
        'basin_length_m':basin_length,'main_channel_length_m':main_length,'main_channel_slope_m_m':channel_slope,
        'total_drainage_length_m':sum(lengths),'stream_segments':len(lengths),
        'drainage_density_km_km2':sum(lengths)/1000/(area/1e6),
        'drainage_frequency_per_km2':len(lengths)/(area/1e6),'maximum_order':int(vals.max()) if vals.size else 0,
        'form_factor':area/basin_length**2 if basin_length else None,
        'elongation_ratio':2*math.sqrt(area/math.pi)/basin_length if basin_length else None,
        'circularity_ratio':4*math.pi*area/perimeter**2 if perimeter else None,
        'compactness_coefficient':perimeter/(2*math.sqrt(math.pi*area)),
        'hypsometric_integral':(mean-low)/(high-low) if high>low else None}
    table=pd.DataFrame([metrics]); csv=ctx.directory/'morphometry.csv'; xlsx=ctx.directory/'morphometry.xlsx'; gpkg=ctx.directory/'morphometry.gpkg'
    table.to_csv(csv,index=False); table.to_excel(xlsx,index=False)
    gpd.GeoDataFrame(table,geometry=[geom],crs=profile['crs']).to_file(gpkg,layer='basin',driver='GPKG')
    if main_geometry is not None:
        gpd.GeoDataFrame({'length_m':[main_length]},geometry=[main_geometry],crs=profile['crs']).to_file(gpkg,layer='main_channel',driver='GPKG',mode='a')
    return Layer(str(csv),kind='table',metadata={'metrics':metrics,'artifacts':[str(xlsx),str(gpkg)],
        'basin_length_definition':'maximum straight distance from outlet to basin boundary',
        'main_channel_definition':'longest routed stream path to outlet',
        'frequency_definition':'segments between junctions per km2; depends on extraction threshold'})
