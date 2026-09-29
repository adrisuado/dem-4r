# Pendiente geográfica y carpeta de salida — 29 de septiembre de 2026

Se incorporó el cálculo de pendiente directamente en DEM geográficos, conservando
la cuadrícula de entrada. Se añadió una fila visible para elegir, abrir o restablecer
la carpeta de salida. La selección se guarda en el proyecto y se transmite a las
ejecuciones individuales, lotes y ubicación inicial de exportación manual.

## Método

Horn (ocho vecinos) y Zevenbergen–Thorne (diferencias centrales) se calculan con
NumPy/SciPy. Para CRS proyectados se utilizan las resoluciones métricas X/Y. En
geográficas, PyProj calcula distancias geodésicas en el elipsoide del CRS por fila:
X entre longitudes separadas una celda a la latitud central; Y entre los bordes
norte/sur de la celda. Esas distancias normalizan las derivadas. Las unidades
angulares del CRS se convierten a grados antes de usar Geod; las elevaciones
declaradas en pies se convierten a metros antes de calcular la pendiente.

Salida en grados: atan(hypot(zx, zy)); salida porcentual: 100 × hypot(zx, zy).
Se mantienen la política de NoData, los bordes NoData por defecto y la alternativa
local. Se rechazan rasters rotados, ejes incompatibles y latitudes fuera de rango.
La metadata conserva modelo de distancias, elipsoide y rango métrico de celda.

El enfoque toma como referencia la documentación de
[terra::terrain](https://rspatial.github.io/terra/reference/terrain.html).
La implementación es propia y no requiere R. No se afirma igualdad numérica
exacta con terra: aquí se corrigen ambos ejes por fila y se usa el elipsoide del
CRS. No se realizó comparación ejecutando el paquete terra en R.

## Validación

- Suite completa: **77 pruebas aprobadas**, incluidos planos proyectados,
  pendiente geográfica a 0°, −12°, 60° y 85°, ambos métodos, grados/porcentaje,
  conversión de pies, ceros válidos, NoData, bordes y rechazo de georreferencias
  inválidas. Las advertencias son de deprecación de dependencias.
- Persistencia de carpeta, lectura de proyectos antiguos, reutilización de caché
  tras cambiar destino, aislamiento de lotes y exportación real desde el selector
  de la interfaz. Se verifica escritura en el destino antes de procesar.
- Prueba real sobre el recorte ANADEM de Yanacancha: **1171 × 1381 píxeles** en
  **EPSG:4326**, manteniendo CRS y transformación original.
- **865 241 pendientes válidas**; mínimo 0°, máximo 70,354528°, media 11,641813°.
  Estadísticas del resultado completo de ese recorte, no del ANADEM completo.
- Cadena **Pendiente → Reclasificar → Poligonizar → Disolver** completada sin
  errores; sus cuatro productos se exportaron dentro de la carpeta seleccionada.
- Revisión visual de la interfaz renderizada con Qt offscreen: selector visible,
  mapa de pendientes, histograma y cuatro nodos completados. No se cerró ni
  modificó una sesión abierta del usuario.

Evidencia local en `test-output/geographic_slope_20260929/`: `verification.json`,
`pendiente_geografica_salida.png`, proyecto de prueba y `salidas_elegidas/`.
Reproducir con `.venv/Scripts/python.exe scripts/verify_geographic_slope.py`;
admite `--input` y `--output`. Los proyectos de trabajo del usuario se conservan.

## Uso

Guarde el proyecto abierto y reinicie con `Iniciar_DEM.cmd`. Puede conectar el
recorte EPSG:4326 directamente al nodo Pendiente. En **Carpeta de salida → Elegir
carpeta…**, indique el destino y seleccione **Finales** o **Detallado**. Los
productos se ordenan por categoría y ejecución. **Usar proyecto** restaura el
destino original; temporales y registros permanecen en el proyecto.

Las otras derivadas métricas conservan sus requisitos previos de CRS proyectado.
