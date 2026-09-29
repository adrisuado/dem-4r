# Cambios solicitados — 29 de septiembre de 2026

## Funcionalidades entregadas

1. **Mapa que ocupa el panel.** Márgenes de pantalla fijos, proporción espacial
   conservada y selector **Llenar vista / Ver toda la extensión**. El primer modo
   llena el espacio visible mediante zoom; puede recortar los extremos del raster.
   Extensión completa permite volver a ver todos los datos.
2. **Histograma automático.** Se muestra al cargar un DEM, abrir un proyecto y
   cambiar las capas visibles. Para rasters mayores de un millón de píxeles se
   usa una muestra regular acotada y se indica expresamente que es aproximada.
   No se confunde tamaño de muestra con población total.
3. **Herramientas agrupadas.** Botones separados para Preprocesamiento, Relieve,
   Hidrología, Álgebra raster, Vectores y Cuencas.
4. **Ocho tipos de salida.** INT8, UINT8, INT16, UINT16, INT32, UINT32, FLOAT32 y
   FLOAT64. Se rechazan fracciones en enteros, desbordamientos y colisiones de
   NoData. Un raster UINT8 con las 256 clases válidas conserva su NoData mediante
   máscara explícita.
5. **Intervalos elegibles por fila.** `[a,b>`, `<a,b]`, `[a,b]` y `<a,b>`.
   Se conservan las reglas de workflows/CSV anteriores basadas en booleanos.
   Importación/exportación CSV nueva con columna `interval` y validación de
   solapamientos antes de guardar el nodo.
6. **Recortes geográficos y extensiones vectoriales.** Máscaras y DEM pueden tener
   CRS diferentes. El buffer en metros se calcula en un CRS métrico local cuando
   la entrada es geográfica. El recorte por extensión admite vector de entrada,
   límites con CRS explícito y margen fijo en metros por lado. La salida conserva
   el CRS y cuadrícula del raster; no se aproxima con una constante metros/grado.
7. **Flujo en ventana independiente.** Se puede maximizar, editar y volver a
   acoplar. Es el mismo editor y conserva conexiones y estados.
8. **Flujos portátiles con variables.** Exportación `.demflow.json`, importación
   con formulario para reemplazar todos los insumos y pestaña para modificar
   parámetros. Compatibilidad con JSON anteriores. Los archivos de datos se
   seleccionan en destino; la receta no incrusta gigabytes de raster.

## Comprobaciones

- **63 pruebas aprobadas**, sin fallos ni pruebas omitidas. Incluyen los 35 casos
  anteriores y 28 casos nuevos para tipos, NoData, intervalos, recortes con CRS
  diferentes, conversión métrica a latitudes distintas, muestreo, importación de
  variables y desacoplamiento del editor.
- Revisión visual de mapa/histograma, ventana del grafo, reclasificación y formulario
  de variables mediante capturas Qt offscreen. Se corrigió el recorte horizontal
  de la columna Intervalo encontrado en la primera captura.
- Prueba real con `anadem_v1_18L.tif` y `distrito_yanacancha.shp`, referenciados en
  el proyecto del usuario. Los archivos originales y su proyecto no se sobrescribieron.
- **Máscara + 30 m:** salida EPSG:4326, 1381 × 1171 píxeles y 871769 píxeles válidos.
- **Extensión vectorial + 200 m por lado:** salida EPSG:4326, 1395 × 1183 píxeles.
- **Histograma del DEM original:** 673580066 píxeles en total, muestra regular de
  999570 posiciones, 793416 válidas. Valores estadísticos y frecuencias aproximados,
  rotulados como muestra en la aplicación.

Evidencia local:

```text
test-output/updates_20260929/tests.xml
test-output/updates_20260929/report.json
test-output/updates_20260929/01_mapa_histograma.png
test-output/updates_20260929/02_flujo_independiente.png
test-output/updates_20260929/03_intervalos.png
test-output/updates_20260929/04_variables.png
test-output/updates_20260929/clip_mask/result.tif
test-output/updates_20260929/clip/result.tif
```

## Cómo usarlo

Cierre la instancia anterior después de guardar su proyecto y vuelva a abrir
`Iniciar_DEM.cmd`. Las instancias ya abiertas conservan el código anterior hasta
reiniciarlas.

Para reutilizar el flujo: **Workflow → Exportar flujo completo**. En el destino,
**Workflow → Importar / reutilizar flujo** y seleccione los nuevos insumos. Para
cambiar entradas del flujo actual, use **Entradas y variables**.

Se incluye `examples/relieve_por_mascara.demflow.json`: recorte por máscara,
reproyección, suavizado, pendiente porcentual, reclasificación UINT8, poligonización
y disolución. Su CRS inicial es EPSG:32718; ajústelo cuando cambie de zona.

El recorte geográfico conserva EPSG:4326. La actualización posterior permite
pendiente directamente en geográficas; curvaturas y otras medidas métricas mantienen
la validación de CRS proyectado. La plantilla conserva su paso de reproyección.
La expansión métrica local
se limita a extensiones menores de 30° por eje; no es una operación geodésica global.

Las estadísticas muestreadas describen la banda completa representada, no solo el
rectángulo que queda visible tras hacer zoom. No modifican los datos de procesamiento.
