from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import re
import uuid


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f'.{uuid.uuid4().hex}.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def safe_name(value):
    return re.sub(r'[^\w.-]+', '_', str(value)).strip('._') or 'resultado'


@dataclass
class Symbology:
    ramp: str = 'terrain'
    stretch: str = 'percentile'
    minimum: float | None = None
    maximum: float | None = None
    opacity: float = 1.0
    classes: int = 5
    breaks: list[float] = field(default_factory=list)
    band: int = 1


@dataclass
class Layer:
    path: str
    name: str = ''
    kind: str = 'raster'
    temporary: bool = True
    metadata: dict = field(default_factory=dict)
    style: Symbology = field(default_factory=Symbology)
    visible: bool = True

    def __post_init__(self):
        self.path = str(Path(self.path).resolve())
        self.name = self.name or Path(self.path).stem
        if isinstance(self.style, dict):
            self.style = Symbology(**self.style)


@dataclass
class ProcessingNode:
    algorithm: str
    inputs: dict[str, str] = field(default_factory=lambda: {'dem': '$dem'})
    parameters: dict = field(default_factory=dict)
    name: str = ''
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    enabled: bool = True
    export: str = 'inherit'
    output_dtype: str = 'float64'
    output_nodata: float | None = None

    def __post_init__(self):
        self.name = self.name or self.algorithm


@dataclass
class Workflow:
    nodes: list[ProcessingNode] = field(default_factory=list)
    name: str = 'Nuevo flujo'
    export_policy: str = 'final'
    prefix: str = ''
    suffix: str = ''
    schema_version: int = 1

    def ordered(self):
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError('Los identificadores de nodo deben ser únicos.')
        if self.export_policy not in ('none', 'final', 'detailed'):
            raise ValueError('Política de exportación desconocida.')
        for n in self.nodes:
            if n.export not in ('inherit', 'temporary', 'always'):
                raise ValueError(f'{n.name}: política de nodo inválida.')
            for ref in n.inputs.values():
                if not ref.startswith('$') and ref not in ids:
                    raise ValueError(f'{n.name}: dependencia inexistente {ref}.')
        remaining, output = list(self.nodes), []
        while remaining:
            ready = [n for n in remaining if all(r.startswith('$') or r in {x.id for x in output} for r in n.inputs.values())]
            if not ready:
                raise ValueError('El flujo contiene un ciclo. Las conexiones deben formar un DAG.')
            output.extend(ready)
            remaining = [n for n in remaining if n not in ready]
        return output

    def terminal_ids(self):
        active = [n for n in self.nodes if n.enabled]
        referenced = {r for n in active for r in n.inputs.values()}
        return {n.id for n in active if n.id not in referenced}

    def save(self, path):
        self.ordered()
        atomic_json(path, asdict(self))

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        if data.get('schema_version', 1) != 1:
            raise ValueError('Versión de workflow no compatible.')
        data['nodes'] = [ProcessingNode(**n) for n in data.get('nodes', [])]
        workflow = cls(**data)
        workflow.ordered()
        return workflow

    @classmethod
    def load(cls, path):
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('format')=='dem-workflow':
            from .workflow_bundle import load_bundle
            return load_bundle(path)[0]
        return cls.from_dict(data)


@dataclass
class Project:
    root: Path
    workflow: Workflow = field(default_factory=Workflow)
    sources: dict[str, str] = field(default_factory=dict)
    layers: list[Layer] = field(default_factory=list)
    vertical_unit: str = 'm'
    output_directory: str | None = None

    def __post_init__(self):
        self.root = Path(self.root).resolve()
        for folder in ('workflows', 'input', 'temporary', 'relief', 'hydrology', 'vectors', 'tables', 'logs'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    @property
    def output_root(self):
        return (self.root / Path(self.output_directory).expanduser()).resolve() if self.output_directory else self.root

    def validate_output_directory(self):
        if self.output_root.is_relative_to(self.root/'temporary'):
            raise ValueError('Seleccione una carpeta fuera de temporary: esa carpeta se puede limpiar al cerrar el proyecto.')
        if self.output_root.exists() and not self.output_root.is_dir():
            raise ValueError('La salida debe ser una carpeta, no un archivo.')

    def save(self):
        self.validate_output_directory()
        def relative(path):
            try:
                return str(Path(path).relative_to(self.root))
            except ValueError:
                return str(Path(path).resolve())
        layers = [asdict(l) for l in self.layers]
        for l in layers:
            l['path'] = relative(l['path'])
        atomic_json(self.root / 'project.json', {
            'schema_version': 1, 'workflow': asdict(self.workflow),
            'sources': {k: relative(v) for k, v in self.sources.items()},
            'layers': layers, 'vertical_unit': self.vertical_unit,
            'output_directory': relative(self.output_root) if self.output_directory else None})

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        d = json.loads(path.read_text(encoding='utf-8'))
        if d.get('schema_version') != 1:
            raise ValueError('Versión de proyecto no compatible.')
        def absolute(p):
            return str((path.parent / p).resolve())
        for layer in d['layers']:
            layer['path'] = absolute(layer['path'])
        return cls(path.parent, Workflow.from_dict(d['workflow']),
                   {k: absolute(v) for k, v in d['sources'].items()},
                   [Layer(**l) for l in d['layers']], d.get('vertical_unit', 'm'),
                   absolute(d['output_directory']) if d.get('output_directory') else None)
