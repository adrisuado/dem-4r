# Microcuencas por tramos D8

Implementación y verificación: 5 de octubre de 2026.

## Uso

Reinicie la aplicación y seleccione **Plantillas → Microcuencas por tramos D8**.
El asistente solicita un DEM monobanda con CRS conocido; puede utilizar el DEM
actual o elegir otro archivo. Revise el CRS proyectado en metros. Puede conservar
el CRS métrico del DEM o elegir un UTM apropiado. La sugerencia basada en el centro
del DEM no comprueba automáticamente la idoneidad de una proyección para toda la zona.

| Parámetro | Inicial | Significado |
|---|---:|---|
| Resolución | 60 m | Cuadrícula utilizada por todos los procesos hidrológicos |
| Contribución mínima | 0,45 km² | Inicio de cauces; equivale a 125 celdas de 60 × 60 m |
| Área mínima final | 0,10 km² | Filtro por parte poligonal después del recorte y separación |
| AOI | Opcional | `$mask`: límite poligonal con CRS, transformado automáticamente |
| Margen del AOI | 5 000 m | Amplía la extensión de trabajo; no es el buffer del resultado final |
| Prefijo de IDs | `MB-` | Editable en el último nodo |

Sin AOI se utiliza el DEM completo. Con AOI se recorta primero su envolvente
ampliada; **no se enmascara el relieve al límite administrativo antes de enrutar**.
El resultado vectorial sí se recorta al AOI exacto, sin margen. Si el GeoPackage
contiene varias capas, use un archivo con el AOI como capa única/primera; el selector
actual de la aplicación no ofrece selección de subcapas.

Al aceptar se construye el flujo. Si ya existe otro, la interfaz permite confirmar
su reemplazo. Revise la unidad Z, elija carpeta de salida y pulse **Ejecutar**.
La política inicial es **Finales**: exporta el GeoPackage final. **Detallado** también
exporta intermedios. Los nodos se editan individualmente y el flujo puede exportarse
como `.demflow.json`, reasignando `$dem` y, cuando corresponde, `$mask` al reutilizarlo.

## Secuencia

```text
DEM + AOI opcional
  → Recorte por extensión del AOI + margen (solo si hay AOI)
  → Reproyección métrica, 60 m, average
  → Fill pits + fill depressions + resolve flats
  → Dirección D8 → Acumulación en km² → Cauces ≥ 0,45 km²
  → Separar tramos D8 (direction + streams)
  → Delimitar microcuencas por tramo (direction + links)
  → Poligonizar con conectividad 4
  → Disolver por value
  → Recortar al AOI opcional, separar partes, calcular áreas,
    filtrar por 0,10 km² y asignar MB_ID
```

Son 10 nodos sin AOI y 11 con AOI. La entrada y los intermedios deben respetar el
límite de lectura completa de la aplicación (25 millones de celdas por defecto).
Un DEM continental debe recortarse a un dominio razonable; la visualización reducida
no reduce por sí sola el tamaño del cálculo. Disminuir resolución no evita el coste
de leer el dominio de origen antes del remuestreo.

## Adaptación del script aportado

Referencia: `01_delinea_microcuencas.py` proporcionado por el usuario. Sus rutas
personales y su EPSG:32717 fijo se sustituyen por variables y parámetros del proyecto.
Se reutilizan las operaciones existentes de la aplicación y su motor pysheds.

Se mantienen la resolución inicial, la equivalencia física del umbral, el filtro de
área y el orden recorte final → explode → área → filtro. Se corrigen/adaptan:

- **Conectividad hidrológica:** el script usa componentes conexos de ocho vecinos
  después de retirar confluencias; eso puede agrupar cauces paralelos adyacentes.
  La aplicación sigue los receptores D8 efectivos. Una confluencia inicia el tramo
  aguas abajo, en lugar de formar un tramo de una sola celda como en el script.
  Por ello no se pretende reproducir idénticos IDs, conteos o geometrías del original.
- **Bordes:** un receptor fuera del raster o sobre NoData se considera salida.
  No se fuerza mediante `np.clip` hacia otra celda del borde.
- **Propagación:** un orden topológico calculado con Kahn y recorrido inverso
  sustituye las 26 iteraciones fijas de salto de punteros. Los ciclos se rechazan.
- **NoData:** se usa la máscara real y valores finitos; no un umbral de altura `>-9000`.
- **Trazabilidad:** se conservan `LINK`, parámetros, motor, cobertura, descartes y
  avisos en la metadata, más exportación/caché/cancelación del flujo existente.
- **Compatibilidad:** no se parchea NumPy ni se silencian globalmente advertencias.

El módulo nuevo `dem_tool/algorithms/microbasins.py` aporta tres procesos:
`stream_links`, `subcatchments` y `finalize_microbasins`.

## Significado del resultado

Cada celda recibe el ID del **primer tramo de cauce alcanzado aguas abajo**.
Las áreas son disjuntas en raster: el tramo inferior no absorbe otra vez todas las
microcuencas superiores. Para una cuenca completa desde una salida use la herramienta
existente **Delimitar cuenca**, con dirección y punto de salida.

El GeoPackage contiene la capa `microcuencas`:

| Campo | Interpretación |
|---|---|
| `MB_ID` | ID único en esa salida (`MB-00001`, etc.); no es un identificador universal estable entre parametrizaciones |
| `LINK` | Tramo raster de origen; puede repetirse al separar partes de un mismo tramo |
| `AREA_KM2` | Área de la geometría final en km², después de recortarla |

Las piezas inferiores al umbral se descartan, **no se agregan a vecinas**. Un AOI,
los huecos del DEM y el borde del dominio pueden cortar áreas de aporte. El margen
de 5 km es un valor inicial y no demuestra que toda la contribución externa esté
contenida. Las celdas que no alcanzan un cauce quedan NoData y se cuentan explícitamente.
No debe esperarse cobertura completa del AOI tras el filtro de superficie.

## Verificación ejecutada

La suite general aprobó **102 pruebas**, incluidas 15 nuevas para esta adaptación:
cauces paralelos, confluencias, asignación local, ciclos, bordes, NoData, validación
de parámetros, flujo con/sin AOI, áreas, exportación, reutilización de caché,
variables portables y asistente gráfico.

Se ejecutó además `scripts/verify_microbasins.py` con ANADEM 18L y el límite de
Yanacancha, usando EPSG:32718, 60 m y los demás parámetros iniciales:

| Indicador observado | Resultado |
|---|---:|
| Nodos ejecutados | 11; sin errores |
| Cuadrícula de enrutamiento | 749 × 843 |
| Tramos en el dominio ampliado | 2 566 |
| Celdas válidas asignadas | 627 255 / 630 463 (99,491 %) |
| Celdas válidas sin cauce alcanzable | 3 208 |
| Polígonos finales dentro del AOI | 814 |
| Área total final | 748,667845 km² |
| Mediana de área final | 0,7236 km² |
| Partes descartadas por área | 825 |
| Área fuera del AOI | 0 m² |
| Diferencia suma de áreas − unión | 2,38 × 10⁻⁷ m² (redondeo numérico) |

Hubo avisos: 168 celdas de dirección sin resolver, aportes no asignados, dominio
potencialmente truncado, recorte al AOI y descarte de partes pequeñas. **Sin errores
de ejecución no significa sin limitaciones hidrológicas.** Estos resultados son una
prueba en Yanacancha, no una reproducción de los resultados del script en Cajamarca.
La evidencia y captura quedan en `test-output/microbasins_20261005/`.

El algoritmo de acondicionamiento, D8 y acumulación procede de
[pysheds](https://github.com/mdbartos/pysheds); la segmentación y asignación por
tramos se implementan y prueban en el código propio de esta aplicación.
