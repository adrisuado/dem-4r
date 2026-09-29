# Decisiones previas a la implementación

El proyecto parte de la especificación Especificacion_App_Procesamiento_DEM.md.
Python 3.11+ y PySide6 componen una aplicación de escritorio local. Rasterio/GDAL
se encargan de E/S y transformaciones, SciPy de filtros, GeoPandas/Shapely de
vectores y pysheds de hidrología. No se implementa un enrutador hidrológico propio.

## Resolución de ambigüedades

- Algoritmo: función registrada sin dependencia de Qt; nodo: configuración
  serializable y entradas nombradas; resultado: archivo y metadatos. La simbología
  reside en un objeto separado y no participa en la clave de procesamiento.
- Un nodo desactivado bloquea sus descendientes; no sustituye implícitamente su
  salida por la entrada, porque podría cambiar el tipo o significado del dato.
- Finales significa terminales del DAG activo. Un nodo temporal nunca se exporta
  automáticamente; «siempre» prevalece incluso sobre la política global Ninguno.
- Los productos múltiples se expresan como nodos separados o artefactos auxiliares
  declarados. La plantilla de curvaturas crea tres nodos reutilizando la entrada.
- Pendiente admite DEM geográficos usando distancias geodésicas X/Y por fila en
  el elipsoide del CRS (PyProj/PROJ), sobre la cuadrícula original. Las restantes
  derivadas métricas requieren reproyección. Un factor Z constante no corrige la
  variación latitudinal del grado; las unidades verticales se declaran y convierten.
- Se aceptan píxeles rectangulares con distancias X/Y separadas. Los rasters rotados
  deben rectificarse mediante reproyección antes de calcular derivadas.
- NoData se representa internamente como NaN; las salidas llevan máscara explícita.
  El valor cero sigue siendo dato válido en pendientes, cuencas y drenajes.
- La acumulación D8 incluye la propia celda. La dirección usa la convención ESRI
  (E=1, SE=2, S=4, SW=8, W=16, NW=32, N=64, NE=128), declarada en metadatos.
- El acondicionamiento registra por separado relleno físico y perturbación mínima
  para resolver planos; esta última no se utiliza para el volumen rellenado.
- Lotes usan el mismo motor y JSON del modo individual; cada fila tiene su propia
  carpeta. Los errores de una fila no impiden ejecutar las demás.

## Objetos y persistencia

`Workflow` valida IDs, dependencias, ciclos y puertos. `Pipeline` ordena el DAG,
calcula hashes de archivos/parámetros/versiones, administra caché persistente y
exporta. `Project` guarda fuentes, capas, estilos y workflow en JSON versionado.
Los logs JSONL incluyen errores y tiempos, y cada salida recibe un sidecar JSON.
`Project.output_directory` es opcional: los proyectos antiguos exportan en su raíz.
La carpeta elegida solo cambia los productos permanentes; caché y logs conservan su
ubicación. Los lotes propagan el destino por ejecución y fila, con rutas distintas.
Las escrituras de manifiestos son atómicas; la caché solo acepta resultados completos.

La GUI contiene árbol de capas, mapa Matplotlib/Qt, estadísticas/histograma,
editor de nodos y conexiones, formularios por algoritmo y tabla de lotes. Un
trabajador Qt ejecuta el motor fuera del hilo de interfaz. La cancelación se
comprueba entre nodos y en filtros iterativos; una llamada nativa en curso debe
terminar antes de devolver el control.

## Verificación

Pruebas numéricas con planos analíticos y NoData; seguridad de calculadora;
ciclos/caché/exportación; ambos DAG de aceptación sobre GeoTIFF; lotes y
persistencia; arranque y renderizado de la GUI con plataforma Qt offscreen.
Los DEM sintéticos son exclusivamente fixtures de prueba, nunca resultados
presentados al usuario como terreno real.

## Fuentes técnicas

- https://rasterio.readthedocs.io/en/stable/topics/reproject.html
- https://rasterio.readthedocs.io/en/stable/api/rasterio.features.html
- https://github.com/pysheds/pysheds
- https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html

Los motores alternativos pueden registrarse con el mismo contrato sin modificar
la GUI. Geomorphons, openness, sky-view factor, MRVBF, MRRTF, HAND, TWI, SPI,
STI y LS quedan como extensiones futuras explícitas, según el alcance inicial.
