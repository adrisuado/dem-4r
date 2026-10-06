from .registry import REGISTRY, Algorithm, register


def load_algorithms():
    from . import preprocessing, terrain, raster_math, vectors, hydrology, morphometry, microbasins
    return REGISTRY
