"""DEM Tool: procesamiento independiente de la interfaz."""
import os
from pathlib import Path

# Keep runtime caches in a writable local workspace, not global user configuration.
_runtime=Path(os.environ.get('DEM_TOOL_CACHE',str(Path.cwd()/'workspace'/'.runtime')))
_runtime.mkdir(parents=True,exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR',str(_runtime/'matplotlib'))
os.environ.setdefault('NUMBA_NUM_THREADS','2')
__version__ = "0.1.0"
