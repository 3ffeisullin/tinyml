"""REQ-FEAT-04: filter chain behaviour."""
import numpy as np
import pytest

from eegml import filters
from eegml.config import FS, FilterSpec


def gain_db(freq, spec=FilterSpec(), seconds=20):
    t = np.arange(int(seconds * spec.fs)) / spec.fs
    y = filters.apply(np.sin(2 * np.pi * freq * t), spec)
    settled = y[len(y) // 2:]
    return 20 * np.log10(np.sqrt(2) * settled.std())


@pytest.mark.parametrize("f", [2.0, 6.0, 10.0, 13.0, 20.0, 30.0])
def test_passband_within_1db(f):
    assert abs(gain_db(f)) < 1.0


@pytest.mark.parametrize("f", [60.0, 120.0])
def test_mains_and_harmonic_rejected(f):
    assert gain_db(f) < -30


def test_dc_offset_removed():
    y = filters.apply(np.full(int(20 * FS), 1650.0))
    assert abs(y[-int(FS):]).max() < 1.0


def test_50hz_option_for_european_data():
    assert gain_db(50.0, FilterSpec(line_freq=50.0)) < -30


def test_sos_shape_for_firmware():
    sos = filters.design_sos()
    # 2 notches + 1 high-pass + 2 low-pass biquads
    assert sos.shape == (5, 6)
