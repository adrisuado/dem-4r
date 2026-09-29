# Especificación para Codex Astra — Aplicación SIG de procesamiento DEM

## 1. Objetivo general

Desarrollar una **aplicación SIG de escritorio especializada en procesamiento de Modelos Digitales de Elevación (DEM)**, orientada a la generación reproducible de productos de:

- relieve y geomorfometría;
- hidrología derivada de DEM;
- álgebra raster especializada;
- preprocesamiento y acondicionamiento de DEM;
- ejecución individual y por lotes;
- visualización, inspección y exportación de resultados.

La aplicación debe permitir que un usuario SIG configure procesos mediante una interfaz visual, los encadene en un flujo, ejecute dicho flujo y reutilice exactamente la misma configuración sobre uno o muchos DEM.

El sistema debe priorizar:

1. facilidad de uso;
2. trazabilidad;
3. automatización;
4. reproducibilidad;
5. consistencia espacial;
6. extensibilidad futura.

---

# 2. Rol que debe asumir el desarrollador

Actúa como:

- desarrollador senior de aplicaciones SIG;
- especialista en procesamiento raster;
- especialista en geomorfometría;
- especialista en hidrología DEM;
- desarrollador Python y R para automatización espacial;
- diseñador de interfaces técnicas orientadas a usuarios GIS;
- arquitecto de software modular.

Para la primera versión se debe priorizar **Python** como lenguaje principal.

Tecnologías sugeridas:

- PySide6 / Qt para GUI;
- Rasterio / GDAL para raster;
- NumPy;
- SciPy;
- GeoPandas;
- Shapely;
- PyProj;
- WhiteboxTools, GRASS GIS o SAGA GIS para algoritmos robustos;
- Matplotlib para histogramas;
- una librería de visualización cartográfica compatible con Qt.

No desarrollar algoritmos complejos desde cero cuando existan implementaciones ampliamente validadas.

---

# 3. Cuatro decisiones de diseño obligatorias

Estas decisiones son parte central de la arquitectura y no deben tratarse como opciones secundarias.

## 3.1 El pipeline es el núcleo real del programa

La aplicación no debe concebirse como una colección de botones independientes.

Debe concebirse como un **constructor de flujos de procesamiento DEM**, similar conceptualmente a un ModelBuilder especializado.

Ejemplo:

```text
DEM
 ↓
Fill gaps
 ↓
Smooth ×2
 ├── Slope
 │    └── Reclassify
 │          └── Polygonize
 │                └── Dissolve
 ├── TPI 500 m
 ├── TPI 1500 m
 ├── Curvature
 └── Flow accumulation
```

Cada proceso debe ser un nodo dentro de un **grafo dirigido acíclico (DAG)**.

El sistema debe identificar dependencias y evitar recalcular nodos ya resueltos.

Ejemplo:

```text
                ┌── Slope
DEM → Smooth ───┼── TPI
                └── Curvature
```

`Smooth` se ejecuta una sola vez.

---

## 3.2 Procesamiento y visualización deben estar desacoplados

Un cambio de simbología nunca debe recalcular un raster.

Debe existir una separación conceptual clara entre:

```text
DATOS
  ↓
PROCESAMIENTO
  ↓
RESULTADO
  ↓
VISUALIZACIÓN
```

Ejemplo:

- cambiar una rampa de color;
- modificar stretch;
- cambiar transparencia;
- cambiar número de clases;

no debe modificar el raster subyacente.

El resultado raster y su representación cartográfica deben ser objetos independientes.

---

## 3.3 Escala, resolución y unidades espaciales deben ser controladas

La aplicación debe validar antes de cualquier operación dependiente de distancia:

- CRS;
- unidad horizontal;
- unidad vertical;
- resolución X;
- resolución Y;
- factor Z;
- tamaño de celda;
- NoData.

No se debe permitir silenciosamente una operación incorrecta.

Ejemplo:

```text
ADVERTENCIA

El DEM se encuentra en coordenadas geográficas.

La pendiente requiere que las unidades horizontales sean
compatibles con la unidad vertical.

Opciones:
[ Reproyectar ahora ]
[ Configurar factor Z ]
[ Cancelar ]
```

Los procesos multiescala deben permitir definir vecindad en:

- píxeles;
- metros;
- unidades del CRS.

Ejemplo:

```text
TPI
Radio: 500
Unidad: metros
```

y no solamente:

```text
Radio: 5 píxeles
```

---

## 3.4 Separar Algoritmo, Nodo y Resultado

La arquitectura debe diferenciar claramente:

```text
ALGORITMO
   ↓
NODO DEL PIPELINE
   ↓
RESULTADO
```

### Algoritmo

Ejemplo:

```text
SlopeAlgorithm
```

Sabe calcular pendiente.

No conoce la interfaz.

### Nodo

Ejemplo:

```text
ProcessingNode
```

Sabe:

- qué algoritmo ejecutar;
- cuál es su entrada;
- qué parámetros usar;
- qué nodo lo precede;
- cuál será su política de exportación.

### Resultado

Ejemplo:

```text
RasterLayer
```

Representa:

- raster generado;
- metadatos;
- estadísticas;
- simbología;
- ruta temporal o permanente.

Esta separación debe permitir añadir posteriormente motores alternativos:

```text
Python
Whitebox
GRASS
SAGA
R
QGIS Processing
```

sin reconstruir la interfaz.

---

# 4. Arquitectura conceptual

```text
GUI
│
├── Main Window
│   ├── Layer Panel
│   ├── Map Viewer
│   ├── Statistics Panel
│   ├── Pipeline Editor
│   └── Process Dialogs
│
├── Project Manager
│
├── Processing Engine
│   ├── Pipeline Manager
│   ├── Dependency Manager
│   ├── Execution Manager
│   └── Cache Manager
│
├── Algorithms
│   ├── Preprocessing
│   ├── Terrain
│   ├── Hydrology
│   └── Raster Math
│
├── Data Model
│   ├── RasterLayer
│   ├── VectorLayer
│   ├── ProcessingNode
│   ├── Workflow
│   └── Project
│
└── I/O
    ├── Raster I/O
    ├── Vector I/O
    ├── Export
    ├── Logs
    └── Metadata
```

---

# 5. Wireframe principal propuesto

## 5.1 Vista individual

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Archivo | Proyecto | Procesamiento | Visualización | Herramientas | Configuración | Ayuda         │
├────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Modo: [● Individual] [○ Lotes]    Proyecto: DEM_Arequipa_01       DEM activo: DEM_10m.tif         │
├──────────────────────┬───────────────────────────────────────────────┬─────────────────────────────┤
│ CAPAS / RESULTADOS   │                                               │ ESTADÍSTICAS / PROPIEDADES   │
│                      │                                               │                             │
│ ENTRADAS             │                                               │ Capa: DEM_smooth             │
│ ☑ DEM_original       │                                               │                             │
│ ☑ mascara            │                MAPA INTERACTIVO               │ Min: 2287.4 m               │
│                      │                                               │ Max: 5821.7 m               │
│ TEMPORALES           │        Zoom / Pan / Identify / Extent         │ Media: 3564.2 m             │
│ ☑ DEM_fill           │                                               │ SD: 318.7                   │
│ ☑ DEM_smooth         │                                               │ NoData: -9999               │
│                      │                                               │                             │
│ RESULTADOS           │                                               │ Resolución: 10 x 10 m        │
│ ☑ slope_deg          │                                               │ CRS: EPSG:32719              │
│ ☑ TPI_500m           │                                               │                             │
│ ☑ curvature          │                                               │ ┌─────────────────────────┐ │
│ ☐ drainage           │                                               │ │       HISTOGRAMA         │ │
│                      │                                               │ │         ▄▄▄               │ │
│ [ + Capa ]           │                                               │ │      ▄█████▄              │ │
│                      │                                               │ └─────────────────────────┘ │
│                      │                                               │ Bins: [50 ▼]                │
├──────────────────────┴───────────────────────────────────────────────┴─────────────────────────────┤
│ FLUJO DE PROCESAMIENTO                                                                            │
│                                                                                                   │
│  [DEM] → [Fill gaps] → [Smooth ×2] ─┬→ [Slope] → [Reclass] → [Polygonize] → [Dissolve]           │
│                                     ├→ [TPI 500 m]                                                 │
│                                     └→ [Curvature]                                                 │
│                                                                                                   │
│ [+ Preproceso] [+ Relieve] [+ Hidrología] [+ Raster Math] [+ Plantilla]                            │
│                                                                                                   │
│ Exportación: [Finales ▼]   Carpeta: C:\Proyecto\outputs\     [▶ Ejecutar] [■ Cancelar]            │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5.2 Vista por lotes

Debe reutilizar el mismo pipeline.

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Archivo | Proyecto | Procesamiento | Visualización | Herramientas | Configuración | Ayuda         │
├────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Modo: [○ Individual] [● Lotes]    Workflow: relieve_basico.json                                   │
├────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ENTRADAS DE LOTE                                                                                   │
│                                                                                                   │
│ ┌────┬────────────────────┬────────────────────┬─────────────┬──────────┬────────────────────────┐ │
│ │ ID │ DEM                │ Máscara            │ Estado      │ Progreso │ Salida                 │ │
│ ├────┼────────────────────┼────────────────────┼─────────────┼──────────┼────────────────────────┤ │
│ │ 01 │ dem_01.tif         │ mask_01.gpkg       │ Completado  │ 100 %    │ output/01/             │ │
│ │ 02 │ dem_02.tif         │ mask_02.gpkg       │ Ejecutando  │  63 %    │ output/02/             │ │
│ │ 03 │ dem_03.tif         │ mask_03.gpkg       │ En espera   │   0 %    │ output/03/             │ │
│ └────┴────────────────────┴────────────────────┴─────────────┴──────────┴────────────────────────┘ │
│                                                                                                   │
│ [+ Añadir DEM] [+ Añadir carpeta] [+ Importar tabla] [Validar lote]                               │
├────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ FLUJO REUTILIZADO                                                                                  │
│                                                                                                   │
│ [DEM] → [Reproject] → [Clip] → [Smooth ×2] ─┬→ [Slope] → [Reclass]                               │
│                                              ├→ [TPI]                                              │
│                                              └→ [Curvature]                                        │
│                                                                                                   │
│ Política: [Finales ▼]          Paralelismo: [2 procesos ▼]          [▶ Ejecutar lote]             │
├────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ DEM 02/12     Proceso actual: TPI     ████████████████░░░░ 63 %     Tiempo: 00:03:42             │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

# 6. Wireframes de ventanas de parámetros

Cada proceso debe abrir su propia ventana de configuración.

Todas las ventanas deben compartir una estructura consistente.

---

## 6.1 Pendiente

```text
┌──────────────────────────────────────────────┐
│ PENDIENTE                                    │
├──────────────────────────────────────────────┤
│ Entrada                                      │
│ Raster: [ DEM_smooth ▼ ]                     │
│                                              │
│ Configuración                                │
│ Unidad de salida: [ Grados ▼ ]               │
│ Método:           [ Horn ▼ ]                 │
│                                              │
│ Unidad horizontal detectada: metros          │
│ Unidad vertical: [ metros ▼ ]                │
│ Factor Z:       [ 1.000 ]                    │
│                                              │
│ Tratamiento de bordes:                       │
│ [●] NoData                                   │
│ [○] Estimación local                         │
│                                              │
│ Salida                                       │
│ Nombre: [ slope_deg ]                        │
│ Tipo:   [ Float32 ▼ ]                        │
│ NoData: [ -9999 ]                            │
│                                              │
│ Exportación                                  │
│ [●] Heredar política global                  │
│ [○] Temporal                                 │
│ [○] Exportar siempre                         │
│                                              │
│ [Vista previa]          [Cancelar] [Guardar] │
└──────────────────────────────────────────────┘
```

Si se selecciona porcentaje:

```text
Unidad de salida: Porcentaje
```

la aplicación debe advertir que valores elevados pueden superar 100 %.

---

## 6.2 TPI

```text
┌──────────────────────────────────────────────┐
│ TOPOGRAPHIC POSITION INDEX — TPI             │
├──────────────────────────────────────────────┤
│ Entrada: [ DEM_smooth ▼ ]                    │
│                                              │
│ Escala                                       │
│ Radio: [ 500 ]                               │
│ Unidad: [ metros ▼ ]                         │
│                                              │
│ Ventana                                      │
│ Forma: [ Circular ▼ ]                        │
│                                              │
│ Normalización                                │
│ [ ] Estandarizar resultado                   │
│                                              │
│ Salida                                       │
│ Nombre automático: TPI_500m                  │
│ Nombre: [ TPI_500m ]                         │
│                                              │
│ MULTIESCALA                                  │
│ [ ] Calcular múltiples radios                │
│ Radios: [ 100 ; 500 ; 1000 ]                │
│                                              │
│ [Vista previa]          [Cancelar] [Guardar] │
└──────────────────────────────────────────────┘
```

---

## 6.3 Curvatura

```text
┌──────────────────────────────────────────────┐
│ CURVATURA                                    │
├──────────────────────────────────────────────┤
│ Entrada: [ DEM_smooth ▼ ]                    │
│                                              │
│ Productos                                   │
│ ☑ Curvatura general                          │
│ ☑ Curvatura de perfil                        │
│ ☑ Curvatura en planta                        │
│ ☐ Curvatura tangencial                       │
│                                              │
│ Método: [ Zevenbergen & Thorne ▼ ]           │
│                                              │
│ Salida                                       │
│ [●] Archivos separados                       │
│ [○] Raster multibanda                        │
│ [○] Ambos                                    │
│                                              │
│ Prefijo: [ curv_ ]                           │
│                                              │
│ [Cancelar]                       [Guardar]    │
└──────────────────────────────────────────────┘
```

---

## 6.4 Suavizado

```text
┌──────────────────────────────────────────────┐
│ SUAVIZADO DEL DEM                            │
├──────────────────────────────────────────────┤
│ Entrada: [ DEM_original ▼ ]                  │
│                                              │
│ Método: [ Mediana ▼ ]                        │
│ Kernel: [ 3 x 3 ▼ ]                          │
│ Iteraciones: [ 2 ]                           │
│                                              │
│ Para Gaussiano:                              │
│ Sigma: [ 1.0 ]                               │
│                                              │
│ NoData                                       │
│ [●] Ignorar NoData en ventana                │
│ [○] Propagar NoData                          │
│                                              │
│ Nombre: [ DEM_smooth ]                       │
│                                              │
│ [Vista previa]          [Cancelar] [Guardar] │
└──────────────────────────────────────────────┘
```

---

## 6.5 Relleno de gaps / NoData

```text
┌──────────────────────────────────────────────┐
│ RELLENO DE GAPS                              │
├──────────────────────────────────────────────┤
│ Entrada: [ DEM_original ▼ ]                  │
│                                              │
│ Método: [ Media local ▼ ]                    │
│ Radio máximo: [ 5 ] píxeles                  │
│ Iteraciones máximas: [ 10 ]                  │
│                                              │
│ Tamaño máximo del gap                        │
│ [ 100 ] píxeles                              │
│                                              │
│ [✓] Mantener gaps mayores como NoData        │
│                                              │
│ Salida: [ DEM_fill ]                         │
│                                              │
│ [Vista previa]          [Cancelar] [Guardar] │
└──────────────────────────────────────────────┘
```

---

## 6.6 Reclasificación

```text
┌──────────────────────────────────────────────────────────────┐
│ RECLASIFICACIÓN                                             │
├──────────────────────────────────────────────────────────────┤
│ Entrada: [ slope_deg ▼ ]                                    │
│                                                              │
│ Reglas                                                       │
│ ┌──────────┬──────────┬──────────┬─────────────────────────┐ │
│ │ Desde    │ Hasta    │ Valor    │ Intervalo               │ │
│ ├──────────┼──────────┼──────────┼─────────────────────────┤ │
│ │ 0        │ 5        │ 1        │ [a,b)                   │ │
│ │ 5        │ 15       │ 2        │ [a,b)                   │ │
│ │ 15       │ 30       │ 3        │ [a,b)                   │ │
│ │ 30       │ 90       │ 4        │ [a,b]                   │ │
│ └──────────┴──────────┴──────────┴─────────────────────────┘ │
│                                                              │
│ [+ Fila] [- Fila] [Importar CSV] [Exportar plantilla]       │
│                                                              │
│ Valores no considerados: [ NoData ▼ ]                       │
│                                                              │
│ Salida: [ slope_class ]                                     │
│                                                              │
│ [Vista previa]                       [Cancelar] [Guardar]     │
└──────────────────────────────────────────────────────────────┘
```

---

## 6.7 Fill depressions

```text
┌──────────────────────────────────────────────┐
│ ACONDICIONAMIENTO HIDROLÓGICO                │
├──────────────────────────────────────────────┤
│ Entrada: [ DEM_smooth ▼ ]                    │
│                                              │
│ Método: [ Fill depressions ▼ ]               │
│ Motor:  [ WhiteboxTools ▼ ]                  │
│                                              │
│ Parámetros                                   │
│ Máxima profundidad opcional: [ automático ] │
│                                              │
│ Diagnóstico                                  │
│ [✓] Generar raster diferencia                │
│ [✓] Reportar volumen rellenado               │
│                                              │
│ Salida: [ DEM_hydro ]                        │
│                                              │
│ [Cancelar]                       [Guardar]    │
└──────────────────────────────────────────────┘
```

---

## 6.8 Flow accumulation

```text
┌──────────────────────────────────────────────┐
│ FLOW ACCUMULATION                            │
├──────────────────────────────────────────────┤
│ Entrada: [ DEM_hydro ▼ ]                     │
│                                              │
│ Dirección: [ D8 ▼ ]                          │
│                                              │
│ Unidad de salida                             │
│ [○] Número de celdas                         │
│ [●] m²                                       │
│ [○] ha                                       │
│ [○] km²                                      │
│                                              │
│ Log-transform para visualización             │
│ [✓] Solo simbología                          │
│                                              │
│ Salida: [ flow_acc ]                         │
│                                              │
│ [Cancelar]                       [Guardar]    │
└──────────────────────────────────────────────┘
```

---

## 6.9 Extracción de drenaje

```text
┌──────────────────────────────────────────────┐
│ EXTRACCIÓN DE RED DE DRENAJE                 │
├──────────────────────────────────────────────┤
│ Entrada: [ flow_acc ▼ ]                      │
│                                              │
│ Umbral                                       │
│ Valor: [ 2.5 ]                               │
│ Unidad: [ km² contribuyentes ▼ ]             │
│                                              │
│ Salida                                       │
│ ☑ Raster                                     │
│ ☑ Vector                                     │
│                                              │
│ Ordenamiento                                 │
│ [✓] Calcular Strahler                        │
│ [ ] Calcular Shreve                          │
│                                              │
│ Nombre: [ drainage ]                         │
│                                              │
│ [Vista previa]          [Cancelar] [Guardar] │
└──────────────────────────────────────────────┘
```

---

# 7. Panel de flujo

El panel inferior debe ser un verdadero editor de workflow.

Funciones mínimas:

- añadir nodo;
- eliminar nodo;
- editar nodo;
- duplicar nodo;
- activar/desactivar nodo;
- reordenar;
- conectar;
- desconectar;
- cambiar entrada;
- cambiar nombre;
- definir política de exportación.

Ejemplo de nodo:

```text
┌───────────────────────┐
│ Slope                 │
│ Input: DEM_smooth     │
│ Units: Degrees        │
│ Method: Horn          │
│ Export: Final         │
│ Status: Ready         │
└───────────────────────┘
```

Estados:

```text
Ready
Running
Completed
Warning
Error
Blocked
Cancelled
```

---

# 8. Política de exportación

Debe existir un control global:

```text
Exportación:
[ Ninguno | Finales | Detallado ]
```

## Ninguno

No exportar automáticamente.

## Finales

Exportar solamente nodos terminales.

## Detallado

Exportar cada resultado.

Cada nodo puede sobrescribir esta política.

---

# 9. Gestión de resultados temporales

Todo resultado temporal debe:

- aparecer en el árbol de capas;
- poder visualizarse;
- poder ser utilizado como entrada;
- poder exportarse manualmente;
- almacenarse en una carpeta temporal administrada.

Al cerrar:

```text
¿Eliminar resultados temporales?
[ Sí ] [ No ]
```

---

# 10. Preprocesamiento

Implementar:

- fill gaps;
- filtros;
- recorte por extensión;
- recorte por máscara;
- buffer;
- reproyección;
- remuestreo;
- asignación de NoData;
- revisión de CRS;
- factor Z.

---

# 11. Relieve / geomorfometría

MVP:

- slope;
- aspect;
- hillshade;
- curvature;
- profile curvature;
- plan curvature;
- TRI;
- TPI;
- roughness;
- VRM;
- local relief.

Preparar arquitectura para:

- geomorphons;
- openness;
- sky-view factor;
- valley depth;
- MRVBF;
- MRRTF;
- convergence index.

---

# 12. Calculadora raster especializada

Debe permitir expresiones como:

```text
A - mean(A)
```

```text
(A - mean(A)) / std(A)
```

```text
(A - min(A)) / (max(A) - min(A))
```

```text
where(A > percentile(A, 90), 1, 0)
```

Funciones mínimas:

```text
min()
max()
mean()
median()
std()
percentile()
where()
log()
sqrt()
abs()
```

Validar la expresión antes de ejecutar.

---

# 13. Hidrología

Flujo base:

```text
DEM
 ↓
Hydrological conditioning
 ↓
Flow direction
 ↓
Flow accumulation
 ↓
Stream extraction
 ↓
Stream ordering
 ↓
Watershed
 ↓
Morphometry
```

MVP:

- fill depressions;
- D8 flow direction;
- flow accumulation;
- stream extraction;
- Strahler;
- watershed;
- snap pour point.

Preparar para:

- D∞;
- MFD;
- HAND;
- TWI;
- SPI;
- STI;
- LS;
- valley depth.

---

# 14. Morfometría de cuenca

Calcular:

- área;
- perímetro;
- elevación mínima;
- máxima;
- media;
- relieve;
- pendiente media;
- longitud de cuenca;
- cauce principal;
- longitud del cauce principal;
- pendiente del cauce;
- densidad de drenaje;
- frecuencia de drenaje;
- orden máximo;
- factor de forma;
- elongación;
- circularidad;
- compacidad;
- integral hipsométrica.

Exportar a:

- CSV;
- XLSX;
- GeoPackage.

---

# 15. Visualización

Funciones:

- zoom;
- pan;
- identify;
- zoom full;
- zoom layer;
- coordenadas;
- superposición raster/vector.

Ramps:

### Continuas

- terrain;
- viridis;
- magma;
- inferno;
- grayscale;
- elevation;
- blue-red.

### Discretas

- equal interval;
- quantile;
- manual.

Configuración:

- min;
- max;
- stretch;
- opacity;
- NoData.

---

# 16. Estadísticas

Mostrar:

- mínimo;
- máximo;
- media;
- mediana;
- SD;
- percentiles;
- píxeles válidos;
- NoData;
- histograma.

Bins:

```text
10
20
50
100
Personalizado
```

Utilizar caché para no recalcular innecesariamente.

---

# 17. Procesamiento por lotes

Debe usar exactamente el mismo workflow individual.

Admitir:

```text
DEM_01
DEM_02
DEM_03
```

y pares:

```text
DEM_01 + mask_01
DEM_02 + mask_02
DEM_03 + mask_03
```

Permitir:

- selección múltiple;
- carpeta;
- tabla CSV;
- validación previa;
- progreso;
- cancelación;
- logs.

---

# 18. Nomenclatura

Formato por defecto:

```text
{input}_{process}
```

Ejemplos:

```text
DEM_slope
DEM_TPI_500m
DEM_flowacc
DEM_curv_profile
```

Permitir:

```text
Prefix
Suffix
```

Ejemplo:

```text
AREQ_DEM_slope_10m.tif
```

---

# 19. Logs y trazabilidad

Cada ejecución debe registrar:

- input;
- algoritmo;
- parámetros;
- CRS;
- resolución;
- unidad Z;
- biblioteca;
- fecha;
- duración;
- warnings;
- errores.

Ejemplo de metadata:

```json
{
  "input": "DEM_10m.tif",
  "process": "slope",
  "algorithm": "Horn",
  "units": "degrees",
  "z_factor": 1,
  "engine": "GDAL",
  "timestamp": "..."
}
```

---

# 20. Estructura de proyecto

```text
Proyecto/
├── project.json
├── workflows/
├── input/
├── temporary/
├── relief/
├── hydrology/
├── vectors/
├── tables/
└── logs/
```

---

# 21. Estructura de código

```text
dem_tool/
│
├── main.py
│
├── gui/
│   ├── main_window.py
│   ├── map_view.py
│   ├── layer_panel.py
│   ├── statistics_panel.py
│   ├── pipeline_panel.py
│   └── dialogs/
│
├── core/
│   ├── project.py
│   ├── workflow.py
│   ├── pipeline.py
│   ├── processing_node.py
│   ├── raster_layer.py
│   └── metadata.py
│
├── algorithms/
│   ├── preprocessing/
│   ├── terrain/
│   ├── hydrology/
│   └── raster_math/
│
├── batch/
│   └── batch_processor.py
│
├── io/
│   ├── raster_io.py
│   ├── vector_io.py
│   ├── exporters.py
│   └── logging.py
│
├── resources/
└── tests/
```

---

# 22. Caso mínimo de aceptación

Debe poder ejecutarse:

```text
DEM
 ↓
Reproject
 ↓
Clip
 ↓
Smooth ×2
 ├── Slope
 │    ↓
 │  Reclass
 │    ↓
 │ Polygonize
 │    ↓
 │ Dissolve
 │
 ├── TPI
 │
 └── Curvature
```

Al terminar:

- visualizar todos los resultados;
- actualizar estadísticas;
- mostrar histogramas;
- mantener temporales;
- exportar según política;
- guardar el workflow;
- volver a ejecutarlo;
- aplicarlo por lotes.

También debe ejecutar:

```text
DEM
 ↓
Fill depressions
 ↓
Flow direction
 ↓
Flow accumulation
 ↓
Stream extraction
```

sin intervención manual intermedia.

---

# 23. Estrategia de implementación

Antes de escribir código:

1. revisar requisitos;
2. detectar conflictos;
3. definir arquitectura;
4. seleccionar dependencias;
5. definir objetos principales;
6. construir el modelo DAG;
7. definir persistencia del proyecto;
8. crear wireframe funcional;
9. implementar GUI base;
10. implementar motor de procesamiento;
11. implementar algoritmos;
12. integrar batch;
13. escribir tests.

No crear toda la aplicación en un solo archivo.

No usar resultados simulados para aparentar funcionalidad.

Cada módulo debe ejecutarse realmente sobre GeoTIFF.

---

# 24. Prioridades del MVP

Implementar primero:

1. carga DEM;
2. visualización;
3. árbol de capas;
4. estadísticas;
5. histograma;
6. reproyección;
7. clip;
8. fill gaps;
9. smooth;
10. slope;
11. aspect;
12. hillshade;
13. curvature;
14. TRI;
15. TPI;
16. roughness;
17. reclassify;
18. raster calculator;
19. fill depressions;
20. flow direction;
21. flow accumulation;
22. stream extraction;
23. pipeline DAG;
24. temporal/permanent outputs;
25. batch.

---

# 25. Restricción de alcance inicial

No intentar construir en la primera iteración:

- un reemplazo completo de QGIS;
- un editor vectorial general;
- un motor hidrodinámico;
- herramientas de teledetección no relacionadas con DEM;
- algoritmos experimentales sin validación;
- una arquitectura excesivamente distribuida.

La aplicación debe tener una identidad clara:

> **Plataforma especializada para construir, ejecutar y reutilizar flujos reproducibles de procesamiento geomorfométrico e hidrológico derivados de DEM.**
