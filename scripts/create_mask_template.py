from pathlib import Path
from dem_tool.core.models import Workflow,ProcessingNode as Node
from dem_tool.core.workflow_bundle import export_bundle

w=Workflow(name='Relieve por máscara · entradas reemplazables',nodes=[
    Node('clip_mask',id='clip',inputs={'dem':'$dem','mask':'$mask'},parameters={'buffer_m':30},name='recorte'),
    Node('reproject',id='projected',inputs={'dem':'clip'},parameters={'crs':'EPSG:32718'},name='DEM_UTM'),
    Node('smooth',id='smooth',inputs={'dem':'projected'},parameters={'iterations':2}),
    Node('slope',id='slope',inputs={'dem':'smooth'},parameters={'units':'percent'}),
    Node('reclassify',id='classes',inputs={'dem':'slope'},parameters={'rules':[[0,5,1,'[a,b)'],[5,15,2,'[a,b)'],[15,30,3,'[a,b)'],[30,200,4,'[a,b]']]},output_dtype='uint8'),
    Node('polygonize',id='polygons',inputs={'dem':'classes'}),
    Node('dissolve',id='dissolved',inputs={'vector':'polygons'})])
export_bundle(Path('examples/relieve_por_mascara.demflow.json'),w,{})
