from copy import deepcopy
from pathlib import Path
from time import sleep, monotonic

import numpy as np
import rasterio
from rasterio.transform import from_origin
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dem_tool.core.models import Project, Workflow, ProcessingNode, Layer
from dem_tool.gui.main_window import MainWindow
from dem_tool.gui.preview import PreviewCache, raster_preview, file_signature
from dem_tool.io.raster_io import StatisticsCache
from test_gui import wait_views


def tree_items(tree):
    return [tree.topLevelItem(i).child(j) for i in range(tree.topLevelItemCount())
            for j in range(tree.topLevelItem(i).childCount())]


def test_bulk_remove_shortcut_undo_preserves_files_sources_order_and_style(tmp_path, dem):
    app = QApplication.instance() or QApplication([])
    layers = [Layer(dem[0], name=f'capa {i}', temporary=False, visible=i == 0) for i in range(3)]
    layers[1].style.opacity = .37
    workflow = Workflow(nodes=[ProcessingNode('slope', id='s')])
    project = Project(tmp_path/'project', workflow, {'$dem': dem[0]}, layers.copy())
    window = MainWindow(project); window.show(); wait_views(window)
    original = deepcopy(workflow)
    items = tree_items(window.layers)
    window.layers.clearSelection(); items[0].setSelected(True); items[1].setSelected(True)
    assert len(window.layers.selected_layers()) == 2
    assert window.remove_layers_button.text() == 'Quitar (2)'
    window.layers.setFocus(); QTest.keyClick(window.layers, Qt.Key.Key_Delete)
    assert len(project.layers) == 1
    assert Path(dem[0]).exists() and project.sources == {'$dem': dem[0]}
    assert project.workflow == original
    assert len(Project.load(project.root/'project.json').layers) == 1
    QTest.keyClick(window.layers, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert all(a is b for a, b in zip(project.layers, layers))
    assert project.layers[1].style.opacity == .37
    assert len(Project.load(project.root/'project.json').layers) == 3
    assert not window.undo_layers_button.isEnabled()
    # Ctrl+A spans all groups, never including group headers as layers.
    QTest.keyClick(window.layers, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert len(window.layers.selected_layers()) == 3
    window.remove_layers_button.click(); wait_views(window)
    assert not project.layers and not window.map.artists and window.statistics.layer is None
    window.undo_layers_button.click(); wait_views(window)
    window.hide(); window.deleteLater(); app.processEvents()


def test_failed_save_does_not_remove_layers(tmp_path, dem, monkeypatch):
    app = QApplication.instance() or QApplication([])
    layer = Layer(dem[0], temporary=False)
    window = MainWindow(Project(tmp_path/'p', layers=[layer])); wait_views(window)
    tree_items(window.layers)[0].setSelected(True)
    errors = []
    monkeypatch.setattr(window, 'inform', errors.append)
    def fail(): raise OSError('disco no disponible')
    monkeypatch.setattr(window.project, 'save', fail)
    window.remove_selected_layers()
    assert errors and window.project.layers == [layer] and not window.removed_layers
    window.hide(); window.deleteLater(); app.processEvents()


def test_repeated_draw_reuses_image_histogram_and_graph(tmp_path, dem):
    app = QApplication.instance() or QApplication([])
    layer = Layer(dem[0], temporary=False)
    project = Project(tmp_path/'p', Workflow(nodes=[ProcessingNode('slope', id='s')]), layers=[layer])
    window = MainWindow(project); window.show(); wait_views(window)
    window.map.draw_layers(project.layers, True); wait_views(window)  # cache viewport
    image = window.map.artists[layer.path]['artists'][0]
    histogram = window.statistics.histogram
    box = window.pipeline._boxes['s']; box.setSelected(True)
    misses = window.map.cache.misses; limits = window.map.ax.get_xlim()
    for i in range(3):
        window.map.draw_layers(project.layers, True); wait_views(window)
        window.pipeline.show_workflow(project.workflow, {'s': 'Running' if i % 2 else 'Completed'})
    assert window.map.artists[layer.path]['artists'][0] is image
    assert window.statistics.histogram is histogram
    assert window.map.cache.misses == misses
    assert window.map.ax.get_xlim() == limits
    assert window.pipeline._boxes['s'] is box and box.isSelected()
    window.statistics.bins.setValue(17); wait_views(window)
    assert window.statistics.histogram is histogram
    assert len(histogram.get_data().values) == 17
    assert len(window.statistics.cache.samples) == 1
    window.hide(); window.deleteLater(); app.processEvents()


def test_slow_preview_is_nonblocking_and_stale_results_discarded(tmp_path, dem, monkeypatch):
    from dem_tool.gui import map_view
    app = QApplication.instance() or QApplication([])
    original = map_view.prepare_layers
    calls = []
    def slow(*args):
        calls.append(args[3]); sleep(.25); return original(*args)
    monkeypatch.setattr(map_view, 'prepare_layers', slow)
    layer = Layer(dem[0], temporary=False)
    window = MainWindow(Project(tmp_path/'p', layers=[layer])); window.show()
    app.processEvents()
    ticks = []
    timer = QTimer(); timer.setInterval(10); timer.timeout.connect(lambda: ticks.append(1)); timer.start()
    QTest.qWait(40)
    layer.visible = False; window.map.draw_layers([layer], True)
    wait_views(window); timer.stop()
    assert len(ticks) >= 5
    assert not window.map.bounds and not window.map.artists and window.statistics.layer is None
    layer.visible = True; window.map.draw_layers([layer]); wait_views(window)
    assert window.map.bounds
    assert len(calls) == 2
    window.hide(); window.deleteLater(); app.processEvents()


def test_viewport_preview_reads_native_detail_without_changing_input(tmp_path):
    path = tmp_path/'detail.tif'
    data = np.arange(1000*1200, dtype='float32').reshape(1000, 1200)
    with rasterio.open(path, 'w', driver='GTiff', width=1200, height=1000, count=1,
                       dtype='float32', crs=32718, transform=from_origin(300000, 8700000, 10, 10)) as dst:
        dst.write(data, 1)
    signature = file_signature(path)
    full = raster_preview(path, 1, 'EPSG:32718', None, 200)
    crop = raster_preview(path, 1, 'EPSG:32718', (301000, 8698000, 302000, 8699000), 200)
    assert max(full['data'].shape) == 200
    assert crop['data'].shape == (100, 100)
    np.testing.assert_array_equal(crop['data'], data[100:200, 100:200])
    assert crop['bounds'] == full['bounds']
    assert file_signature(path) == signature
    outside = raster_preview(path, 1, 'EPSG:32718', (0, 0, 1, 1), 200)
    assert outside['data'] is None


def test_preview_cache_and_statistics_memory_are_bounded(dem):
    cache = PreviewCache(max_bytes=25000, max_entries=2)
    for i in range(8): cache.put((str(i),), {'data': np.ones((40, 40), dtype='float32')})
    assert cache.bytes <= 25000 and len(cache.values) <= 2
    assert cache.get(('0',)) is None and cache.get(('7',)) is not None
    cache.retain({'7'}); assert list(cache.values) == [('7',)]
    cache.retain(set()); assert cache.bytes == 0
    stats = StatisticsCache()
    for bins in range(2, 25): stats.get(dem[0], bins)
    assert len(stats.values) == 16 and len(stats.samples) == 1


def test_new_project_clears_undo_and_ignores_previous_pending_view(tmp_path, dem):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project(tmp_path/'p1', layers=[Layer(dem[0], temporary=False)]))
    wait_views(window); tree_items(window.layers)[0].setSelected(True); window.remove_selected_layers()
    assert window.removed_layers
    window.project = Project(tmp_path/'p2'); window.refresh(); wait_views(window)
    assert not window.removed_layers and not window.map.bounds and window.map.crs is None
    window.restore_layers(); assert not window.project.layers
    window.hide(); window.deleteLater(); app.processEvents()


def test_bulk_visibility_emits_once_and_preserves_selection(tmp_path, dem):
    from dem_tool.gui.layer_panel import LayerPanel
    app = QApplication.instance() or QApplication([])
    panel = LayerPanel(); layers = [Layer(dem[0], name=str(i)) for i in range(3)]
    panel.populate(layers, {}); panel.selectAll()
    events = []; panel.visibility_changed.connect(lambda: events.append(1))
    panel.set_selected_visible(False)
    assert events == [1] and all(not layer.visible for layer in layers)
    panel.populate(layers, {})
    assert len(panel.selected_layers()) == 3
    panel.deleteLater(); app.processEvents()


def test_vector_geometry_cache_reprojects_and_filters_viewport(tmp_path, monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box, LineString, Point
    from dem_tool.gui.preview import vector_preview
    path = str(tmp_path/'mixed.gpkg')
    gpd.GeoDataFrame(geometry=[box(-75.6, -12.4, -75.5, -12.3),
                             LineString([(-75.6, -12.4), (-75.5, -12.3)]),
                             Point(-75.55, -12.35)], crs=4326).to_file(path)
    cache = PreviewCache(); reads = []
    original = gpd.read_file
    def counted(*args, **kwargs):
        reads.append(1); return original(*args, **kwargs)
    monkeypatch.setattr(gpd, 'read_file', counted)
    full = vector_preview(path, 'EPSG:32718', None, 800, cache)
    assert len(full['rings']) == len(full['lines']) == len(full['points']) == 1
    assert full['bounds'][0] > 100000
    outside = vector_preview(path, 'EPSG:32718', (0, 0, 1, 1), 1400, cache)
    assert not outside['rings'] and not outside['lines'] and not len(outside['points'])
    assert full['bounds'] == outside['bounds'] and reads == [1]


def test_zoom_and_resize_keep_center_and_color_scale(tmp_path, dem):
    app = QApplication.instance() or QApplication([])
    layer = Layer(dem[0], temporary=False)
    window = MainWindow(Project(tmp_path/'p', layers=[layer])); window.show(); wait_views(window)
    view = window.map
    image = view.artists[layer.path]['artists'][0]; color_range = image.norm.vmin, image.norm.vmax
    x, y = view.ax.get_xlim(), view.ax.get_ylim()
    center = ((x[0]+x[1])/2, (y[0]+y[1])/2)
    view.ax.set_xlim(center[0]-30, center[0]+30); view.ax.set_ylim(center[1]-30, center[1]+30)
    view.quality.setCurrentIndex(2); wait_views(window)
    window.resize(window.width()+100, window.height()+80); wait_views(window)
    assert abs(sum(view.ax.get_xlim())/2-center[0]) < 1e-6
    assert abs(sum(view.ax.get_ylim())/2-center[1]) < 1e-6
    assert abs(view.ax.get_ylim()[1]-view.ax.get_ylim()[0]-60) < 1e-6
    assert (image.norm.vmin, image.norm.vmax) == color_range
    window.hide(); window.deleteLater(); app.processEvents()
