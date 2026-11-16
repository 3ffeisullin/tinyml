"""REQ-FEAT-06, 07: 30 s epoch aggregation."""
import numpy as np

from eegml import filters
from eegml.config import FS
from eegml.epochs import EPOCH_FEATURE_NAMES, epoch_features
from eegml.features import sliding_features


def test_29_windows_per_epoch_and_shape():
    x = np.random.default_rng(0).standard_normal(int(95 * FS))
    s, f = sliding_features(filters.apply(x), x)
    e, n = epoch_features(s, f, np.array([0, 30, 60]) * int(FS))
    assert e.shape == (3, len(EPOCH_FEATURE_NAMES))
    assert n.tolist() == [29, 29, 29]


def test_epoch_without_windows_is_nan():
    x = np.zeros(int(40 * FS))
    s, f = sliding_features(x)
    e, n = epoch_features(s, f, np.array([40 * int(FS)]))  # starts after the data ends
    assert n[0] == 0 and np.isnan(e).all()
