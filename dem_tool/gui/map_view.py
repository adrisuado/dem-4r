from pathlib import Path
import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform as transform_coords
from matplotlib.figure import Figure
from matplotlib.colors import Normalize, LogNorm, BoundaryNorm
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QComboBox,QLabel
import geopandas as gpd


class MapView(QWidget):
    message=Signal(str)
    plotted_raster=Signal(object)
    def __init__(self):
        super().__init__()
        self.figure=Figure(facecolor='#111c2d')
        self.figure.subplots_adjust(left=.065,right=.985,bottom=.09,top=.975)
        self.canvas=FigureCanvasQTAgg(self.figure)
        self.ax=self.figure.add_subplot(111)
        self.toolbar=NavigationToolbar2QT(self.canvas,self)
        self.framing=QComboBox(); self.framing.addItem('Llenar vista','fill'); self.framing.addItem('Ver toda la extensión','fit')
        self.framing.setToolTip('Llenar vista conserva las proporciones y puede recortar bordes. Extensión completa muestra todos los datos.')
        self.toolbar.addWidget(self.framing)
        self.framing.currentIndexChanged.connect(lambda:self.frame_extent())
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.toolbar); layout.addWidget(self.canvas)
        self.layers=[]; self.selected=None; self.crs=None; self.bounds={}; self.cache={}
        self.canvas.mpl_connect('motion_notify_event',self.coordinates)
        self.canvas.mpl_connect('button_press_event',self.identify)
        self.canvas.mpl_connect('scroll_event',self.scroll)
        self.draw_layers([])
        self.canvas.mpl_connect('resize_event',lambda e:self.frame_extent() if self.bounds else None)

    def draw_layers(self,layers,preserve=False):
        old=(self.ax.get_xlim(),self.ax.get_ylim()) if preserve and self.layers else None
        self.layers=layers; self.ax.clear(); self.bounds={}
        self.ax.set_facecolor('#111c2d'); self.ax.tick_params(colors='#a9bbcc',labelsize=8)
        for spine in self.ax.spines.values(): spine.set_color('#334258')
        visible=[l for l in layers if l.visible and l.kind in ('raster','vector') and Path(l.path).exists()]
        self.crs=None
        last_raster=None
        for l in visible:
            if l.kind=='raster':
                with rasterio.open(l.path) as src: self.crs=src.crs
                if self.crs: break
        for l in visible:
            try:
                stat=Path(l.path).stat(); key=(l.path,stat.st_mtime_ns,str(self.crs),l.style.band)
                if l.kind=='raster':
                    if key not in self.cache:
                        with rasterio.open(l.path) as src:
                            if src.crs and self.crs:
                                with WarpedVRT(src,crs=self.crs) as vrt:
                                    scale=max(vrt.width,vrt.height)/1200
                                    w,h=max(1,int(vrt.width/max(scale,1))),max(1,int(vrt.height/max(scale,1)))
                                    data=vrt.read(l.style.band,out_shape=(h,w),masked=True).astype(float).filled(np.nan)
                                    b=vrt.bounds
                            else:
                                scale=max(src.width,src.height)/1200
                                data=src.read(l.style.band,out_shape=(max(1,int(src.height/max(scale,1))),max(1,int(src.width/max(scale,1)))),masked=True).astype(float).filled(np.nan)
                                b=src.bounds
                        self.cache[key]=(data,b)
                    data,b=self.cache[key]; v=data[np.isfinite(data)]
                    if not v.size: continue
                    style=l.style
                    low=style.minimum if style.minimum is not None else float(np.percentile(v,2) if style.stretch=='percentile' else v.min())
                    high=style.maximum if style.maximum is not None else float(np.percentile(v,98) if style.stretch=='percentile' else v.max())
                    high=max(high,low+1e-12)
                    norm=Normalize(low,high)
                    if style.stretch=='log':
                        positive=v[v>0]
                        if positive.size: norm=LogNorm(max(low,float(positive.min())),max(high,float(positive.min())*1.001))
                    elif style.stretch in ('equal_interval','quantile','manual'):
                        breaks=style.breaks if style.stretch=='manual' else np.quantile(v,np.linspace(0,1,style.classes+1)) if style.stretch=='quantile' else np.linspace(low,high,style.classes+1)
                        breaks=np.unique(breaks)
                        if len(breaks)>1: norm=BoundaryNorm(breaks,256,clip=True)
                    cmap={'elevation':'gist_earth','blue-red':'RdBu_r','grayscale':'gray'}.get(style.ramp,style.ramp)
                    self.ax.imshow(np.ma.masked_invalid(data),extent=(b.left,b.right,b.bottom,b.top),origin='upper',
                                   cmap=cmap,norm=norm,alpha=style.opacity,interpolation='nearest',zorder=visible.index(l)+1)
                    self.bounds[l.path]=(b.left,b.bottom,b.right,b.top)
                    last_raster=l
                else:
                    if key not in self.cache:
                        frame=gpd.read_file(l.path)
                        if self.crs and frame.crs: frame=frame.to_crs(self.crs)
                        self.cache[key]=frame
                    frame=self.cache[key]
                    if not frame.empty:
                        polygons=frame.geometry.geom_type.isin(['Polygon','MultiPolygon'])
                        if polygons.any(): frame[polygons].boundary.plot(ax=self.ax,color='#f8cf63',linewidth=1,alpha=l.style.opacity,zorder=50)
                        if (~polygons).any(): frame[~polygons].plot(ax=self.ax,color='#57ddf2',linewidth=1.4,markersize=35,alpha=l.style.opacity,zorder=51)
                        self.bounds[l.path]=frame.total_bounds
            except Exception as exc:
                self.message.emit(f'Visualización de {l.name}: {exc}')
        if not visible:
            self.ax.text(.5,.55,'DEM / WORKFLOWS',transform=self.ax.transAxes,ha='center',color='#a8cfe0',fontsize=24,weight='bold')
            self.ax.text(.5,.44,'Añade un DEM para explorar el relieve\ny construir un flujo reproducible.',
                         transform=self.ax.transAxes,ha='center',color='#8b9caf',fontsize=12,linespacing=1.7)
            self.ax.set_xticks([]); self.ax.set_yticks([])
        self.ax.set_aspect('equal',adjustable='datalim')
        if old: self.ax.set_xlim(old[0]); self.ax.set_ylim(old[1])
        elif self.bounds: self.frame_extent(last_raster)
        self.canvas.draw_idle()
        self.plotted_raster.emit(last_raster)

    def full_extent(self,layer=None):
        self.framing.blockSignals(True); self.framing.setCurrentIndex(1); self.framing.blockSignals(False)
        self.frame_extent(layer)

    def frame_extent(self,layer=None):
        values=[self.bounds[layer.path]] if layer and layer.path in self.bounds else list(self.bounds.values())
        if values:
            b=np.asarray(values); xmin,ymin=b[:,:2].min(axis=0); xmax,ymax=b[:,2:].max(axis=0)
            width,height=max(xmax-xmin,1e-12),max(ymax-ymin,1e-12)
            ratio=self.ax.bbox.width/max(self.ax.bbox.height,1)
            size=max(height,width/ratio) if self.framing.currentData()=='fit' else min(height,width/ratio)
            size*=1.04 if self.framing.currentData()=='fit' else 1.0
            cx,cy=(xmin+xmax)/2,(ymin+ymax)/2
            self.ax.set_xlim(cx-size*ratio/2,cx+size*ratio/2); self.ax.set_ylim(cy-size/2,cy+size/2); self.canvas.draw_idle()

    def coordinates(self,event):
        if event.inaxes==self.ax and event.xdata is not None:
            self.message.emit(f'X {event.xdata:,.3f}   Y {event.ydata:,.3f}   |   {self.crs or "CRS no definido"}')

    def identify(self,event):
        if event.inaxes!=self.ax or event.button!=1 or self.toolbar.mode or not self.selected: return
        layer=self.selected
        if layer.kind!='raster': return
        try:
            with rasterio.open(layer.path) as src:
                x,y=event.xdata,event.ydata
                if src.crs and self.crs and src.crs!=self.crs:
                    xx,yy=transform_coords(self.crs,src.crs,[x],[y]); x,y=xx[0],yy[0]
                row,col=src.index(x,y)
                value='Fuera de extensión'
                if 0<=row<src.height and 0<=col<src.width:
                    v=src.read(layer.style.band,window=((row,row+1),(col,col+1)),masked=True)[0,0]
                    value='NoData' if np.ma.is_masked(v) else f'{float(v):.8g}'
                self.message.emit(f'{layer.name}  |  fila {row}, columna {col}  |  valor {value}')
        except Exception as exc: self.message.emit(str(exc))

    def scroll(self,event):
        if event.inaxes!=self.ax:return
        factor=.8 if event.button=='up' else 1.25
        x,y=event.xdata,event.ydata
        self.ax.set_xlim([x+(v-x)*factor for v in self.ax.get_xlim()]); self.ax.set_ylim([y+(v-y)*factor for v in self.ax.get_ylim()])
        self.canvas.draw_idle()
