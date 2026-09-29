import numpy as np

INTERVALS={'[a,b)':(True,False),'(a,b]':(False,True),'[a,b]':(True,True),'(a,b)':(False,False)}


def normalize_interval(value):
    # Retain workflows and CSVs saved before explicit interval selection existed.
    if isinstance(value,bool):return '[a,b]' if value else '[a,b)'
    value=str(value).replace(' ','').replace('<','(').replace('>',')').replace('⟨','(').replace('⟩',')')
    if value not in INTERVALS:raise ValueError('Intervalo: [a,b), (a,b], [a,b] o (a,b).')
    return value


def validate_rules(rules):
    normalized=[]
    for row in rules:
        if len(row)!=4:raise ValueError('Cada regla requiere desde, hasta, valor e intervalo.')
        low,high,value=map(float,row[:3]); interval=normalize_interval(row[3])
        if not np.isfinite([low,high,value]).all() or low>=high:raise ValueError('Regla inválida: límites finitos y desde < hasta requeridos.')
        normalized.append([low,high,value,interval])
    normalized.sort(key=lambda row:row[0])
    for previous,current in zip(normalized,normalized[1:]):
        if previous[1]>current[0] or (previous[1]==current[0] and INTERVALS[previous[3]][1] and INTERVALS[current[3]][0]):
            raise ValueError('Los intervalos de reclasificación se superponen.')
    if not normalized:raise ValueError('Añada al menos una regla de reclasificación.')
    return normalized
