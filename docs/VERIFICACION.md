# Verificación de la entrega

Fecha: 28 de septiembre de 2026. Entorno: Windows, Python 3.12.14,
dependencias registradas en `requirements-lock.txt`.

## Resultados ejecutados

| Comprobación | Resultado |
|---|---|
| Suite automatizada | 35 pruebas aprobadas, 0 fallos, 0 omitidas |
| Flujo de relieve de aceptación | 9/9 nodos completados sobre GeoTIFF |
| Flujo hidrológico de aceptación | 4/4 nodos completados sobre GeoTIFF |
| Repetición del relieve | 9/9 nodos recuperados de caché |
| Repetición de hidrología | 4/4 nodos recuperados de caché |
| Lote concurrente con dos entradas | Ambas completadas en carpetas independientes |
| Lote frente a modo individual | Mismos valores, máscaras, transformaciones y CRS en todos los resultados raster |
| Dependencias | `pip check`: sin incompatibilidades declaradas |
| GUI | Carga, formularios, mapa, histograma, grafo y ejecución real mediante QThread comprobados |
| Revisión visual | Captura offscreen inspeccionada; fuentes y etiquetas del grafo corregidas |

La suite comprueba planos de pendiente conocida con píxeles rectangulares,
conversión de pies, curvaturas nulas de planos, TPI/TRI sobre un pico conocido,
NoData, huecos pequeños/grandes, filtros, seguridad del AST, límites de clases,
ciclos, nodos desactivados, cancelación anticipada, ramas con fallos, exportación,
tipos y sentinelas, cambios de parámetros/archivos, caché dañada, persistencia,
recorte por máscara, reproyección, buffer, acumulación y conversión de áreas,
cuenca y ajuste al centro de celda, morfometría, Strahler/Shreve en una confluencia,
multibanda y extracción de bandas.

## Correcciones derivadas de las pruebas

- NumPy 2.5 retiró `np.in1d`, que utiliza pysheds 0.5. Se fijó NumPy 2.2.6.
- El snap se realiza contra centros de celda mediante la función `View.snap_to_mask`
  de pysheds, evitando un desplazamiento de media celda por remuestreo de la máscara.
- Se añadió un borde NoData al enrutamiento de direcciones existente antes de
  delinear cuencas/ordenar redes. Evita perder celdas del perímetro por el manejo
  interno del borde de pysheds. La cuenca y acumulación coinciden en número de celdas.
- Se cargan fuentes de Matplotlib en Qt para garantizar texto legible incluso en
  renderizado offscreen. Se retienen los objetos de texto del grafo para evitar
  que PySide los destruya durante la recolección de objetos.

## Evidencia reproducible

- `test-output/pytest.xml`: informe JUnit de las 35 pruebas.
- `test-output/acceptance/acceptance_report.json`: informe integrado de los flujos.
- `test-output/acceptance/relief/` y `hydrology/`: proyectos, temporales, exportaciones,
  sidecars JSON y logs de las ejecuciones.
- `test-output/acceptance/batch/`: proyectos independientes por fila.
- `test-output/acceptance/gui_relief.png`: captura de la GUI con fixture de prueba.
- `scripts/verify_acceptance.py`: recrea y ejecuta ambos flujos y compara el lote.
- `scripts/capture_gui.py`: vuelve a capturar el proyecto de QA sin recalcular datos.

Los fixtures sintéticos se rotulan **SOLO QA**. El usuario no proporcionó un DEM
de terreno para esta entrega. No se afirma validación de campo, equivalencia
completa con otros motores ni rendimiento probado en archivos de gran tamaño.

Las bibliotecas emiten avisos de deprecación (Affine, Qt, `np.in1d`, driver GDAL
Memory). También se observó un `NotGeoreferencedWarning` durante reproyección
concurrente de arrays. Se verificaron explícitamente CRS, transformación, máscara
y valores de todos los resultados del lote contra la ejecución individual: iguales.
Estos avisos no se ocultan en las ejecuciones de QA.

## Cobertura de la especificación

| Apartados | Entrega |
|---|---|
| 1–4: objetivo, arquitectura y decisiones | GUI PySide6; algoritmo/nodo/capa separados; DAG; validaciones espaciales; estilos independientes |
| 5–6: interfaz y parámetros | Capas, mapa, estadísticas, histograma, grafo, formularios, tabla de reglas, plantillas, vista previa real |
| 7: edición del flujo | Añadir, eliminar, editar, duplicar, activar, reordenar, conectar/desconectar por selector, cambiar nombre/exportación |
| 8–9: exportación y temporales | Ninguno/Finales/Detallado, excepciones por nodo, exportación manual, caché y pregunta de limpieza al cerrar |
| 10: preprocesos | Todos los enumerados; remuestreo dentro de Reproyectar; revisión de CRS en propiedades y errores de validación |
| 11: relieve | Todos los productos MVP, incluida curvatura de perfil/planta, VRM y relieve local; multiescala y multibanda |
| 12: calculadora | Funciones requeridas, validación AST, sin eval, control de alineación y NoData |
| 13: hidrología | Pysheds: relleno, D8, acumulación, drenajes, Strahler, Shreve, watershed y snap |
| 14: morfometría | Variables enumeradas, definiciones explícitas y CSV/XLSX/GeoPackage |
| 15–16: mapa y estadísticas | Zoom/pan/identify/extensiones/coordenadas/superposición; rampas, clases, opacidad, histograma y caché |
| 17: lotes | Mismo JSON y motor, archivos/carpeta/CSV, máscaras, validación, concurrencia, estados/cancelación/logs |
| 18–21: nomenclatura y persistencia | Prefijo/sufijo/ID anticollision, metadatos, proyecto JSON y módulos separados |
| 22: aceptación | Ambos DAG ejecutados y comprobados |
| 23–25: estrategia y alcance | Decisiones previas documentadas; código modular; algoritmos reales; extensiones futuras fuera del MVP |

Las tecnologías descritas como alternativas se concretaron en pysheds para
hidrología. No se muestran motores no instalados como si fueran funcionales.
Las capacidades futuras de los apartados 11 y 13 tienen un registro extensible,
pero sus algoritmos no se anuncian como implementados. El editor utiliza conexiones
mediante formularios; no dispone de arrastre de cables entre puertos.
