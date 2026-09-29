import numpy as np
import pytest
from dem_tool.algorithms.raster_math import calculate,validate_expression
from dem_tool.io.raster_io import read_raster,write_raster
from dem_tool.core.models import Layer


def test_calculator_global_statistics_and_mask():
    a=np.array([[1.,2.,np.nan],[3.,4.,5.]])
    assert np.allclose(calculate('A - mean(A)',{'A':a})[1],[0,1,2])
    out=calculate('where(A > percentile(A, 90), 1, 0)',{'A':a})
    assert np.isnan(out[0,2]) and out[1,2]==1 and out[0,0]==0
    out=calculate('(A-min(A))/(max(A)-min(A))',{'A':a})
    assert out[0,0]==0 and out[1,2]==1


@pytest.mark.parametrize('expression',["__import__('os').system('whoami')",'A.__class__','A[0]','[x for x in A]', 'open(1)', '2 ** (2 ** 16)','mean(A, 1)','lambda:1'])
def test_calculator_rejects_unsafe(expression):
    with pytest.raises(ValueError):validate_expression(expression)


def test_reclassification_boundaries(run_algorithm,dem,tmp_path):
    a=np.resize(np.array([0.,5.,15.,30.,90.,91.]),dem[1].shape)
    path=write_raster(tmp_path/'classes.tif',a,dem[2]); out,_=read_raster(run_algorithm('reclassify',inputs={'dem':Layer(path)}).path)
    assert np.allclose(out.ravel()[:5],[1,2,3,4,4]); assert np.isnan(out.ravel()[5])
