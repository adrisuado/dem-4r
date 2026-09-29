from dataclasses import dataclass, field
from pathlib import Path
import threading
from dem_tool.core.models import Layer
from dem_tool.io.raster_io import read_raster, write_raster


class Cancelled(Exception):
    pass


@dataclass
class Context:
    directory: Path
    cancel: threading.Event
    vertical_unit: str = 'm'
    warnings: list = field(default_factory=list)

    def check(self):
        if self.cancel.is_set():
            raise Cancelled('Ejecución cancelada.')

    def raster(self, data, profile, metadata=None, name='result'):
        self.check()
        path = write_raster(self.directory / f'{name}.tif', data, profile, metadata)
        return Layer(path, metadata=metadata or {})


@dataclass
class Algorithm:
    id: str
    title: str
    category: str
    function: object
    defaults: dict
    ports: dict
    output: str = 'raster'
    help: str = ''
    engine: str = 'NumPy/SciPy'
    optional_ports: dict = field(default_factory=dict)

    def run(self, inputs, params, ctx):
        missing = set(self.ports) - inputs.keys()
        if missing:
            raise ValueError(f'Faltan entradas: {sorted(missing)}')
        for key, kind in self.ports.items():
            if kind != 'any' and inputs[key].kind != kind:
                raise ValueError(f'{key} requiere {kind}, recibió {inputs[key].kind}.')
        for key,kind in self.optional_ports.items():
            if key in inputs and inputs[key].kind!=kind:
                raise ValueError(f'{key} requiere {kind}.')
        unknown = set(params) - self.defaults.keys()
        if unknown:
            raise ValueError(f'Parámetros desconocidos: {sorted(unknown)}')
        return self.function(inputs, self.defaults | params, ctx)


REGISTRY = {}


def register(id, title, category, defaults=None, ports=None, output='raster', help='', engine='NumPy/SciPy',optional_ports=None):
    def decorate(fn):
        REGISTRY[id] = Algorithm(id, title, category, fn, defaults or {},
                                 ports or {'dem': 'raster'}, output, help, engine,optional_ports or {})
        return fn
    return decorate
