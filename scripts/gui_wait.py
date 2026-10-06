"""Espera de vistas asíncronas para capturas de verificación fuera de la GUI."""
from time import monotonic
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest


def wait_views(window, timeout=60):
    """Procesa eventos hasta que mapa e histograma estén listos o vence el plazo."""
    app=QApplication.instance(); end=monotonic()+timeout
    while True:
        app.processEvents()
        if not window.map.loading and not window.statistics.loading:break
        if monotonic()>end:raise TimeoutError('La vista no terminó de cargar.')
        QTest.qWait(10)
    window.map.canvas.draw(); window.statistics.canvas.draw(); app.processEvents()
