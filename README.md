# DEM Workflows

Aplicación SIG de escritorio en español para construir, guardar y ejecutar flujos
de procesamiento de modelos digitales de elevación. Interfaz PySide6, motor Python
sin dependencia de Qt y procesamiento real de GeoTIFF.

## Abrir en este equipo

**Doble clic en `Iniciar_DEM.cmd`.** El entorno `.venv` está instalado dentro del
proyecto. No modifica el Python de ArcGIS ni otras instalaciones del sistema.

Desde PowerShell, situado en la carpeta del proyecto:

```powershell
& '.\.venv\Scripts\python.exe' -m dem_tool gui
```

En otro equipo con Python 3.11 o superior:

```powershell
.\Instalar.ps1 -Python 'C:\ruta\python.exe'
.\Iniciar_DEM.cmd
```

`requirements-lock.txt` registra las versiones comprobadas en Windows/Python 3.12.
Para reproducirlas: instale ese archivo con pip antes de instalar el proyecto
mediante `pip install --no-deps -e .`. NumPy se limita a `<2.3` por el uso de
`np.in1d` en pysheds 0.5.

## Primer flujo

1. Abra **Archivo → Nuevo proyecto** y elija una carpeta. El proyecto inicial se
   crea automáticamente en `workspace/Proyecto_fecha_hora`.
2. Pulse **+ DEM** y seleccione un GeoTIFF de una banda. Declare la unidad vertical
   real: metros, pies internacionales o pies estadounidenses. No se deduce de las
   coordenadas horizontales.
3. Seleccione **Plantillas → Relieve básico**. Indique el CRS proyectado apropiado
   para el DEM. EPSG:32718 es solo el valor inicial del formulario, no una elección
   automática válida para cualquier área.
4. Haga doble clic sobre cada nodo para revisar sus entradas, parámetros, nombre,
   tipo de salida y política de exportación. En **Recortar**, indique
   `[xmin,ymin,xmax,ymax]` en el CRS de trabajo; vacío conserva toda la extensión.
5. En **Carpeta de salida → Elegir carpeta…**, seleccione dónde guardar los
   productos. Elija **Ninguno**, **Finales** o **Detallado** y pulse **Ejecutar**.
6. Consulte las capas temporales, seleccione una para ver estadísticas, y use
   **Simbología** para cambiar colores/contraste. Los cambios de estilo no ejecutan
   algoritmos ni alteran el raster.
7. Use **Workflow → Exportar flujo completo** para reutilizar exactamente el flujo. Los
   proyectos guardan además rutas, capas y estilos.

La plantilla reproduce:

```text
DEM → Reproject → Clip → Smooth ×2 ┬→ Slope → Reclassify → Polygonize → Dissolve
                                 ├→ TPI 500 m
                                 └→ Curvature
```

**Plantillas → Hidrología D8** crea el segundo caso de aceptación:

```text
DEM → Fill depressions → D8 direction → Flow accumulation → Streams
```

Esta plantilla requiere que el DEM ya tenga un CRS proyectado. Añada un nodo de
reproyección y conecte Fill depressions a su salida si hace falta.

## Mapa y capas

- El mapa ocupa todo el panel con márgenes fijos. **Llenar vista** aprovecha el
  espacio manteniendo las proporciones y puede dejar bordes del raster fuera de
  pantalla. **Ver toda la extensión** o **Extensión completa** muestra el raster
  completo; no se estira la geografía para rellenar el panel.
- Rueda para acercar/alejar, herramientas de mano y rectángulo en la barra del mapa.
- Clic sobre el mapa identifica el valor de la capa seleccionada; las coordenadas
  aparecen en la barra inferior. Desactive pan/zoom para identificar.
- Marque o desmarque capas para superponer rasters y vectores. El orden visual de
  raster sigue el orden de carga/resultados; los vectores se dibujan por encima.
- La vista usa una previsualización de hasta 1200 píxeles por lado. Identificación
  y procesamiento usan los datos originales. El histograma se carga automáticamente
  para el raster visible superior, también al abrir un proyecto o cambiar visibilidad.
- Rampa continua, intervalos iguales, cuantiles o límites manuales; stretch min/max,
  percentiles 2–98 o logaritmo; límites personalizados y opacidad.
- El logaritmo de visualización oculta valores no positivos únicamente en el mapa.
- Las estadísticas incluyen población válida/NoData, SD poblacional, mediana y
  percentiles 2/25/50/75/98. El número de bins es configurable de 2 a 1000.
- Hasta un millón de píxeles las estadísticas son exactas. Para rasters mayores se
  usa una muestra regular de hasta un millón de píxeles, con aviso visible de
  aproximación y tamaño de muestra. Los conteos se refieren a esa muestra, no se
  extrapolan como si fueran conteos exactos de todo el DEM. Esta vista no está
  limitada por el máximo de celdas del motor de procesamiento.
- CSV/XLSX de morfometría aparecen como tablas; su GeoPackage auxiliar puede verse
  como vector. Los archivos auxiliares se incluyen en las exportaciones.

## Carpeta de salida

La fila **Carpeta de salida**, encima de Ejecutar, muestra siempre el destino.
**Elegir carpeta…** lo cambia y guarda la selección en el proyecto; **Abrir salida**
abre ese destino y **Usar proyecto** restaura la ubicación original. También se
usa como ubicación inicial al exportar una capa manualmente.

Los productos se organizan en subcarpetas por categoría y ejecución, con nombres
únicos para conservar resultados anteriores. En lotes se añade una carpeta por
ejecución y por DEM. Temporales, caché y registros permanecen en el proyecto.
Cambiar la carpeta permite reutilizar la caché y exportar al nuevo destino.
**Finales** guarda las salidas terminales; **Detallado** también los intermedios;
**Ninguno** conserva solo temporales salvo nodos marcados para exportar siempre.
La receta portátil del flujo no impone una carpeta del equipo de origen.

## Pendiente directamente en geográficas

Puede conectar **Recortar por máscara → Pendiente** sobre EPSG:4326. Declare la
unidad Z real (m, ft o us-ft) y elija Horn o Zevenbergen–Thorne y grados o porcentaje.
No se remuestrea el DEM ni se usa una constante universal de metros por grado.
La salida registra el modelo de distancia, el elipsoide y los tamaños métricos
mínimos/máximos de celda. NoData conserva el tratamiento estricto de vecindad 3×3;
los bordes son NoData por defecto y la opción local replica el borde.

Se adopta el enfoque de distancias elipsoidales documentado por
[terra::terrain](https://rspatial.github.io/terra/reference/terrain.html), con una
implementación propia en NumPy/SciPy y PyProj. No se requiere R. Hay diferencias
intencionales: aquí se utiliza el elipsoide declarado por el CRS y se ajustan
ambas distancias por fila; el código de terra consultado usa WGS84 y una distancia
norte-sur calculada en el ecuador
([implementación consultada](https://raw.githubusercontent.com/rspatial/terra/master/src/distRaster.cpp)).
Por ello no se promete igualdad bit a bit con R.

## Editor de workflow

El editor ofrece vista gráfica y tabla de nodos. Seleccione un nodo y use **Editar /
conectar**, **Duplicar**, **Eliminar**, **Activar**, **↑** o **↓**. Cambie las entradas
en el formulario para conectar o desconectar. Se rechazan ciclos; antes de ejecutar
se comprueban puertos obligatorios y tipos de entrada. Puede guardar nodos sin
conectar, pero debe completar sus entradas antes de ejecutar.

Las herramientas se organizan en seis botones: **Preprocesamiento**, **Relieve**,
**Hidrología**, **Álgebra raster**, **Vectores** y **Cuencas**. Cada uno abre solo
los procesos de su grupo. **Abrir flujo en otra ventana** permite maximizar el
editor y conservar el mapa aparte. Cerrar esa ventana o pulsar **Volver a acoplar**
devuelve el mismo editor al mapa sin perder nodos ni estados de ejecución.

## Exportar y reutilizar un flujo completo

**Workflow → Exportar flujo completo** guarda un `.demflow.json` con todos los
nodos, conexiones, parámetros, nombres, tipos de salida, políticas y variables de
entrada. Es una receta portátil; los rasters y vectores se eligen en el destino,
no se incrustan ni se copian dentro del archivo.

Al usar **Importar / reutilizar flujo**, un formulario permite reemplazar `$dem`,
`$mask` y cualquier otra entrada conectada. **Parámetros reutilizables** permite
modificar CRS de destino, radios, buffers, reglas y demás valores sin reconstruir
el grafo. **Entradas y variables** abre el mismo formulario sobre el flujo actual.
Los flujos JSON de la versión anterior siguen siendo compatibles. **Guardar JSON
clásico** conserva el formato anterior cuando se necesita.

`examples/relieve_por_mascara.demflow.json` incluye recorte geográfico con buffer,
reproyección, suavizado, pendiente, reclasificación, poligonización y disolución.
Reasigne DEM y máscara al importarlo. Su CRS inicial EPSG:32718 corresponde a UTM
18 sur; revise ese parámetro si reutiliza la plantilla en otra zona.

## Recortes y márgenes en metros

**Recortar por máscara** admite DEM y vector geográficos o proyectados. Un buffer
en metros se aplica en las unidades lineales del CRS proyectado, o mediante una
proyección azimutal equidistante local cuando el DEM está en coordenadas geográficas.
La máscara se transforma al CRS del DEM y la salida conserva su cuadrícula y CRS.

**Recortar por extensión** permite conectar un vector en `extent` o seleccionarlo
directamente desde el formulario. Se lee su extensión en el CRS del DEM. También
puede escribir límites e indicar su CRS en **CRS de la extensión**. **Ampliar
extensión** expande los cuatro lados en metros: en un DEM geográfico, se transforma
la envolvente a un CRS métrico local y de vuelta con bordes densificados. No se usa
una constante universal de metros por grado. El margen local admite áreas de hasta
30° por eje; la salida se limita a los píxeles existentes del raster.

El recorte conserva coordenadas geográficas cuando la entrada es geográfica.
**Pendiente** admite esa salida directamente, sin un nodo Reproyectar. Las demás
derivadas métricas mantienen su requisito de CRS proyectado; la plantilla de
relieve con TPI y curvatura incluye ese paso.

La selección de un nodo sirve como entrada inicial al añadir otro. Cada entrada
tiene su propio selector: las operaciones de varios rasters no asumen que todos
deban ser iguales. **+ DEM** conserva los rasters anteriores como `$raster_1`, etc.,
para usarlos como B en la calculadora. `$dem` representa el DEM activo del modo
individual o la fila actual del lote.

Un nodo desactivado bloquea sus dependientes. Reordenar cambia el orden de nodos
independientes; las dependencias siempre gobiernan el orden de ejecución. Un fallo
bloquea su rama y permite que otras ramas independientes terminen.

La vista previa ejecuta realmente el nodo configurado y sus ancestros, sin exportar.
Es un cálculo completo, no un recorte aproximado de la pantalla.

## Catálogo inicial

| Área | Algoritmos disponibles |
|---|---|
| Preproceso | Reproyección/remuestreo, recorte por extensión o máscara, buffer de máscara, asignación de CRS, asignación de NoData, factor Z, fill gaps, filtros |
| Relieve | Pendiente Horn/Zevenbergen–Thorne, aspect, hillshade, curvaturas general/perfil/planta/tangencial, TRI Riley, TPI, rugosidad, relieve local, VRM |
| Álgebra | Calculadora raster segura, reclasificación por intervalos |
| Vector | Poligonización de clases enteras, disolución por campo, buffer métrico |
| Hidrología | Relleno de depresiones, resolución de planos, dirección D8, acumulación, drenaje raster/vector, Strahler, snap pour point, cuenca |
| Cuenca | Morfometría y exportación CSV/XLSX/GeoPackage |

Hay 33 algoritmos registrados. Curvaturas y filtros se configuran por parámetros.
**TPI multiescala** crea un nodo por radio, y **Tres curvaturas** crea general,
perfil y planta compartiendo la misma entrada. **Conjunto de curvaturas** permite
archivos separados, un GeoTIFF multibanda o ambos. Seleccione la banda que desea
visualizar en Simbología; use **Extraer banda** para encadenarla a otro algoritmo.

### Convenciones y unidades

- Pendiente acepta CRS geográfico o proyectado, conservando CRS, extensión,
  resolución y alineación. En geográficas calcula distancias X/Y en metros por
  fila con `pyproj.Geod` y el elipsoide del CRS. Horn usa ocho vecinos;
  Zevenbergen–Thorne usa diferencias centrales. Salida en grados o porcentaje.
- Las otras derivadas métricas requieren CRS proyectado y unidad horizontal
  conocida. Píxeles rectangulares usan distancias X/Y independientes. Los rasters
  rotados deben rectificarse antes de calcular derivadas.
- El factor Z es adicional a la conversión explícita de metros/pies. No sustituye
  el cálculo de distancias horizontales según la latitud.
- TPI: centro menos media de vecinos, excluyendo centro. La opción estandarizada
  divide por SD local; vecindades constantes producen NoData en esa modalidad.
- TRI: raíz de la suma de diferencias cuadráticas (Riley), no media cuadrática.
- Roughness y local relief usan máximo menos mínimo de la vecindad. Los nombres
  se conservan para explicitar el producto; comparten definición en esta versión.
- VRM usa la longitud del vector normal medio. Planos constantes dan cero.
- Curvatura general: `-(zxx + zyy)`. Perfil:
  `-(zxx*zx² + 2*zxy*zx*zy + zyy*zy²) / ((zx²+zy²)*(1+zx²+zy²)^1.5)`.
  Planta: `-(zxx*zy² - 2*zxy*zx*zy + zyy*zx²)/(zx²+zy²)^1.5`.
  Tangencial usa el numerador de planta y denominador
  `(zx²+zy²)*sqrt(1+zx²+zy²)`. Derivadas centrales, unidades 1/m; sin escalado ×100.
  Se declaran estas convenciones porque otros programas emplean signos/escalados
  distintos. En puntos planos se devuelve 0 para las curvaturas direccionales.
- Aspect: azimut de máxima bajada, grados horarios desde norte; planos = NoData.
- Bordes de derivadas: por defecto NoData. La opción local extiende el píxel del
  borde. No estima a través de huecos internos.
- Fill gaps conserva NoData conectado al borde y permite excluir huecos grandes.
  Media iterativa o interpolación IDW de Rasterio; no equivale a rellenar depresiones.
- El relleno hidrológico y los planos utilizan pysheds. El volumen rellenado se
  calcula antes del ajuste mínimo de planos. Una profundidad máxima excedida
  detiene el nodo; no entrega un DEM hidrológicamente incompleto.
- D8: E=1, SE=2, S=4, SW=8, W=16, NW=32, N=64, NE=128. Valores -1/-2 indican
  planos/depresiones sin resolver y se reportan. La acumulación incluye la propia celda.
- Umbrales cells/m²/ha/km² se convierten mediante área de celda real. La acumulación
  conserva la ruta de su dirección para extraer líneas y Strahler.
- Las longitudes de cuenca/cauce y los índices tienen definiciones documentadas
  en el sidecar. Longitud de cuenca = máxima distancia recta salida–borde; cauce
  principal = trayectoria de drenaje más larga hasta la salida. La frecuencia usa
  segmentos entre confluencias, dependientes del umbral. Valores no definidos se
  exportan vacíos, no como ceros inventados.

### Reclasificación y calculadora

Cada regla tiene límites, valor e **Intervalo** seleccionable: `[a,b>`, `<a,b]`,
`[a,b]` o `<a,b>`. Los corchetes incluyen el extremo y los signos angulares lo
excluyen. En JSON se guardan las formas equivalentes `[a,b)`, `(a,b]`, `[a,b]` y
`(a,b)`. Se rechazan solapamientos, incluyendo un límite compartido cerrado en
ambas clases. CSV nuevo: `from,to,value,interval`. Los CSV anteriores con
`include_to` y workflows con booleanos siguen siendo compatibles. Valores no
cubiertos: NoData o conservar original.

```text
A - mean(A)
(A - mean(A)) / std(A)
(A - min(A)) / (max(A) - min(A))
where(A > percentile(A, 90), 1, 0)
where((A > 10) & (B < 30), A, B)
```

Funciones: min, max, mean, median, std, percentile, where, log, sqrt, abs. Estadísticos
ignoran NoData. Se conserva la intersección de píxeles válidos de las variables
utilizadas. Divisiones indefinidas se convierten en NoData. El AST se valida y se
interpreta sin `eval`, acceso a archivos, atributos, índices ni importaciones.

## Hidrología hasta morfometría

1. Ejecute la plantilla hidrológica y revise el umbral de drenaje.
2. Añada **Snap pour point**, conecte la acumulación, declare X/Y en el CRS del
   raster y la tolerancia máxima. También puede cargar un único punto con + Vector.
3. Añada **Watershed**, conecte dirección y punto ajustado.
4. Añada **Strahler** con dirección y raster de drenaje.
5. Añada **Morfometría**, conecte DEM original, cuenca, dirección, drenajes y Strahler.
   Todas las cuadrículas deben coincidir exactamente.

La tabla incluye área, perímetro, cotas, relieve, pendiente media, longitudes,
pendiente del cauce principal, densidad/frecuencia, orden máximo, factor de forma,
elongación, circularidad, compacidad e integral hipsométrica. El GeoPackage incluye
la cuenca y, cuando existe una trayectoria válida, el cauce principal.

## Lotes

Cambie a **Procesamiento por lotes**. Añada archivos, una carpeta o un CSV. Asigne
máscaras mediante doble clic en su columna. Ejemplo:

```csv
dem,mask
datos/dem_01.tif,mascaras/mask_01.gpkg
datos/dem_02.tif,mascaras/mask_02.gpkg
```

Valide el lote y ejecute. Hay de 1 a 8 trabajadores concurrentes; se usan hilos con
archivos/proyectos separados, no procesos distribuidos. Es recomendable comenzar
con 1 para DEM grandes. Cada fila recibe carpeta propia, incluso si los nombres
base se repiten. El informe agregado es `batch_report.json`; un error de fila no
impide terminar las demás. La cancelación es cooperativa: las operaciones nativas
en curso terminan antes de devolver el control.

## Archivos, caché y exportación

```text
Proyecto/
  project.json
  workflows/
  input/
  temporary/<hash>/
  relief/<ejecución>/
  hydrology/<ejecución>/
  vectors/<ejecución>/
  tables/<ejecución>/
  logs/<ejecución>.jsonl
  batch/<ejecución>/
```

Los archivos originales se referencian y no se sobrescriben ni copian implícitamente.
La caché incluye hashes de entradas (y componentes de shapefile), parámetros, unidad
vertical, código y bibliotecas. Verifica también hashes de las salidas antes de
reutilizarlas. Un ancestro compartido se ejecuta una sola vez por DAG. Cambiar un
parámetro invalida ese nodo y sus descendientes.

**Ninguno** conserva solo temporales; **Finales** exporta terminales; **Detallado**
exporta todos. Por nodo: heredar, temporal o siempre. «Siempre» prevalece incluso
sobre «Ninguno». Cada ejecución usa una carpeta nueva para evitar sobrescrituras.
Nombres: `{prefijo}{input}_{nodo}{sufijo}_{id}`; el ID evita colisiones.

Salidas Float64 por defecto. Tipos disponibles: Float32, Float64, Int8, UInt8,
Int16, UInt16, Int32 y UInt32. Los enteros rechazan fracciones y desbordamientos.
NoData automático = NaN en flotantes; en enteros se busca un sentinela libre. Si
todo el rango de un entero está ocupado, se conserva NoData mediante máscara
explícita, sin invalidar el cero u otra clase existente. Puede configurar un
sentinela explícito, con detección de colisiones y validación del rango.
Cada resultado tiene metadatos JSON, versiones, inputs, parámetros, unidades, CRS,
resolución, fecha, duración y advertencias. Los logs registran también fallos.

Al cerrar se pregunta si se eliminan los temporales; la opción predeterminada es
conservarlos. Las exportaciones quedan disponibles. Para continuar una cadena
hidrológica tras borrar temporales, vuelva a ejecutar su workflow; una acumulación
exportada por sí sola no contiene toda su red de dependencias.

## CLI, pruebas y evidencia

```powershell
& '.\.venv\Scripts\python.exe' -m dem_tool algorithms
& '.\.venv\Scripts\python.exe' -m dem_tool run examples/relieve_basico.json --dem C:/datos/dem.tif --output C:/proyectos/relieve
& '.\.venv\Scripts\python.exe' -m dem_tool batch examples/relieve_basico.json --csv C:/datos/lote.csv --output C:/proyectos/lote --workers 2
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' scripts/verify_acceptance.py
```

El script de aceptación genera `test-output/acceptance/`: GeoTIFF sintético rotulado
como fixture de QA, dos proyectos ejecutados, lote, logs, captura de la interfaz y
`acceptance_report.json`. Son pruebas de funcionamiento y consistencia, no una
validación de terreno ni una comparación exhaustiva con QGIS/GRASS.

## Límites explícitos de esta primera versión

- Cálculo en memoria, con límite inicial de 25 millones de celdas por raster. Se
  puede cambiar `DEM_TOOL_MAX_CELLS` según RAM; no hay procesamiento por teselas
  para hidrología. Las vecindades muy grandes pueden ser costosas.
- Sin instalador EXE firmado; el lanzador utiliza el entorno Python local.
- Sin edición vectorial general; se incluyen solo operaciones derivadas del flujo DEM.
- Un solo punto de salida por nodo watershed; varias cuencas requieren varios nodos.
- Pysheds es el motor hidrológico incluido. Whitebox, GRASS, SAGA, R y QGIS son
  futuras integraciones, no opciones simuladas en la interfaz.
- Geomorphons, openness, sky-view factor, valley depth, MRVBF/MRRTF, convergence,
  D∞/MFD, HAND, TWI, SPI, STI y LS quedan fuera de esta primera implementación.
- Strahler y Shreve están implementados mediante las funciones de enrutamiento de
  pysheds; el segundo acumula pesos unitarios desde las cabeceras de drenaje.

Consulte `docs/ARQUITECTURA.md` para decisiones, contratos y fuentes técnicas.
