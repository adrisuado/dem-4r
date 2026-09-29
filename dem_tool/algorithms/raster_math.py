import ast
import operator
import numpy as np
from .registry import register
from dem_tool.io.raster_io import read_raster, align_check
from .intervals import INTERVALS,validate_rules

FUNCTIONS = {'min': np.nanmin, 'max': np.nanmax, 'mean': np.nanmean,
             'median': np.nanmedian, 'std': np.nanstd, 'percentile': np.nanpercentile,
             'where': np.where, 'log': np.log, 'sqrt': np.sqrt, 'abs': np.abs}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
          ast.BitAnd: operator.and_, ast.BitOr: operator.or_}
COMPARE = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt,
           ast.LtE: operator.le, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def validate_expression(expression, names=('A','B')):
    if len(expression) > 2000:
        raise ValueError('Expresión demasiado larga.')
    try:
        tree = ast.parse(expression, mode='eval')
    except SyntaxError as e:
        raise ValueError(f'Expresión inválida: {e.msg}') from e
    if sum(1 for _ in ast.walk(tree)) > 300:
        raise ValueError('Expresión demasiado compleja.')
    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int,float,bool):
            if abs(n.value)>1e100:
                raise ValueError('Constante excesiva.')
        elif isinstance(n, ast.Name) and n.id in names:
            pass
        elif isinstance(n,ast.BinOp) and type(n.op) in BINARY:
            visit(n.left); visit(n.right)
            if isinstance(n.op,ast.Pow) and (not isinstance(n.right,ast.Constant) or abs(n.right.value)>16):
                raise ValueError('Potencia requiere exponente constante entre -16 y 16.')
        elif isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub,ast.Invert)):
            visit(n.operand)
        elif isinstance(n,ast.Compare) and len(n.ops)==1 and type(n.ops[0]) in COMPARE:
            visit(n.left); visit(n.comparators[0])
        elif isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in FUNCTIONS and not n.keywords:
            arity = {'where':3,'percentile':2}.get(n.func.id,1)
            if len(n.args)!=arity:
                raise ValueError(f'{n.func.id} requiere {arity} argumentos.')
            for arg in n.args:
                visit(arg)
        else:
            raise ValueError('Solo se admiten variables raster, números, operadores y funciones autorizadas.')
    visit(tree.body)
    return tree.body


def calculate(expression, variables):
    tree = validate_expression(expression, variables.keys())
    def run(n):
        if isinstance(n,ast.Constant): return float(n.value)
        if isinstance(n,ast.Name): return variables[n.id]
        if isinstance(n,ast.BinOp): return BINARY[type(n.op)](run(n.left),run(n.right))
        if isinstance(n,ast.Compare): return COMPARE[type(n.ops[0])](run(n.left),run(n.comparators[0]))
        if isinstance(n,ast.UnaryOp):
            return {ast.UAdd:operator.pos,ast.USub:operator.neg,ast.Invert:operator.invert}[type(n.op)](run(n.operand))
        return FUNCTIONS[n.func.id](*[run(a) for a in n.args])
    with np.errstate(all='ignore'):
        result = np.broadcast_to(run(tree), next(iter(variables.values())).shape).astype(float).copy()
    used = {n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and n.id in variables}
    valid = np.ones(result.shape,dtype=bool)
    for name in used:
        valid &= np.isfinite(variables[name])
    result[~valid|~np.isfinite(result)] = np.nan
    return result


@register('calculator','Calculadora raster','raster_math',{'expression':'A - mean(A)'}, {'A':'raster'},
          help='Variables A y B (opcional). Funciones: min/max/mean/median/std/percentile/where/log/sqrt/abs. NoData se conserva.')
def calculator(inputs,p,ctx):
    pairs = {k:read_raster(v.path) for k,v in inputs.items()}
    align_check([v[1] for v in pairs.values()])
    result = calculate(p['expression'],{k:v[0] for k,v in pairs.items()})
    return ctx.raster(result,next(iter(pairs.values()))[1],{'expression':p['expression']})


@register('reclassify','Reclasificar','raster_math',
          {'rules':[[0,5,1,'[a,b)'],[5,15,2,'[a,b)'],[15,30,3,'[a,b)'],[30,90,4,'[a,b]']], 'unmatched':'nodata'},
          help='Elija extremos abiertos o cerrados por fila: [a,b), (a,b], [a,b] o (a,b). Se rechazan límites compartidos incluidos en ambas clases.')
def reclassify(inputs,p,ctx):
    a,profile=read_raster(inputs['dem'].path)
    if p['unmatched'] not in ('nodata','keep'):
        raise ValueError('Valores no cubiertos: nodata o keep.')
    out=a.copy() if p['unmatched']=='keep' else np.full_like(a,np.nan)
    rules=validate_rules(p['rules'])
    for r in rules:
        closed_left,closed_right=INTERVALS[r[3]]
        select=((a>=r[0]) if closed_left else (a>r[0])) & ((a<=r[1]) if closed_right else (a<r[1]))
        out[select]=r[2]
    out[~np.isfinite(a)]=np.nan
    return ctx.raster(out,profile,{'units':'class','rules':rules})
