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
