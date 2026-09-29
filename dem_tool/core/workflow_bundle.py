"""Portable workflow recipes: complete graph plus explicit input variables."""
from dataclasses import asdict
from pathlib import Path
import json
from dem_tool.core.models import Workflow,atomic_json
from dem_tool.algorithms import load_algorithms


def input_variables(workflow):
    registry=load_algorithms(); variables={}
    for node in workflow.nodes:
        algorithm=registry[node.algorithm]
        for port,ref in node.inputs.items():
            if ref.startswith('$'):
                kind=(algorithm.ports|algorithm.optional_ports).get(port,'raster')
                if ref in variables and variables[ref]['kind']!=kind:
                    raise ValueError(f'La variable {ref} se utiliza con tipos incompatibles.')
                variables.setdefault(ref,{'kind':kind,'used_by':[],'required':False})
                variables[ref]['used_by'].append(f'{node.name} / {port}')
                variables[ref]['required'] |= node.enabled
    return variables


def export_bundle(path,workflow,sources,vertical_unit='m'):
    workflow.ordered()
    variables=input_variables(workflow)
    for key,info in variables.items():
        info['file_hint']=Path(sources[key]).name if sources.get(key) else ''
    atomic_json(path,{'format':'dem-workflow','bundle_version':1,'workflow':asdict(workflow),
                     'variables':variables,'vertical_unit':vertical_unit})


def load_bundle(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('format')=='dem-workflow':
        if data.get('bundle_version')!=1:raise ValueError('Versión de paquete de flujo no compatible.')
        workflow=Workflow.from_dict(data['workflow'])
        variables=input_variables(workflow)
        for key,info in variables.items():info['file_hint']=data.get('variables',{}).get(key,{}).get('file_hint','')
        return workflow,variables,data.get('vertical_unit','m')
    workflow=Workflow.from_dict(data)
    return workflow,input_variables(workflow),'m'
