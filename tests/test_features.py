"""REQ-FEAT-01..05, 08: window features."""
import numpy as np
import pytest
from scipy import stats

from eegml import filters
from eegml.config import FS, NFFT
from eegml.features import FEATURE_NAMES, moments, sliding_features, window_bounds, window_features

T = np.arange(int(2 * FS)) / FS
I = {n: i for i, n in enumerate(FEATURE_NAMES)}


@pytest.mark.parametrize("freq,band", [(2.0, "delta"), (6.0, "theta"), (10.0, "alpha"),
                                       (13.5, "sigma"), (22.0, "beta")])
def test_pure_tone_lands_in_its_band(freq, band):
    f = window_features(10 * np.sin(2 * np.pi * freq * T))
    assert f[I[f"rel_{band}"]] > 0.9


def test_band_power_scale_matches_signal_power():
    # A 10 uV-amplitude sine has power A^2/2 = 50 uV^2; with this normalisation the
    # summed one-sided spectrum equals mean-square * N, so check the ratio instead.
    x = 10 * np.sin(2 * np.pi * 10 * T)
    f = window_features(x)
    w = np.hanning(len(x))
    expected = np.sum((x * w) ** 2) / np.sum(w ** 2) * NFFT / 2  # Parseval, one-sided
    assert 10 ** f[I["logp_alpha"]] == pytest.approx(expected, rel=0.05)


def test_relative_powers_of_sleep_bands_sum_to_one():
    f = window_features(np.random.default_rng(1).standard_normal(len(T)))
    s = sum(f[I[f"rel_{b}"]] for b in ["delta", "theta", "alpha", "sigma", "beta"])
    assert s == pytest.approx(1.0, abs=0.02)


def test_moments_match_scipy():
    x = np.random.default_rng(2).gamma(2.0, size=500)
    sk, ku = moments(x)
    assert sk == pytest.approx(stats.skew(x))
    assert ku == pytest.approx(stats.kurtosis(x))


def test_skew_kurtosis_reference_shapes():
    rng = np.random.default_rng(3)
    _, ku_gauss = moments(rng.standard_normal(100_000))
    _, ku_sine = moments(np.sin(np.linspace(0, 200 * np.pi, 100_000)))
    sk_exp, _ = moments(rng.exponential(size=100_000))
    assert abs(ku_gauss) < 0.05          # Gaussian: excess kurtosis 0
    assert ku_sine == pytest.approx(-1.5, abs=0.01)
    assert sk_exp == pytest.approx(2.0, abs=0.1)


def test_spike_raises_kurtosis():
    x = np.random.default_rng(4).standard_normal(len(T))
    y = x.copy(); y[250] += 40
    assert window_features(y)[I["kurtosis"]] > window_features(x)[I["kurtosis"]] + 5


def test_window_counts():
    assert len(window_bounds(int(10 * FS))[0]) == 9
    assert window_bounds(int(10 * FS))[1] == 500


def test_line_noise_metric_sees_unfiltered_hum():
    t = np.arange(int(10 * FS)) / FS
    raw = 10 * np.sin(2 * np.pi * 10 * t) + 30 * np.sin(2 * np.pi * 60 * t)
    _, f = sliding_features(filters.apply(raw), raw)
    _, f_clean = sliding_features(filters.apply(raw), filters.apply(raw))
    assert f[-1, I["q_line_ratio"]] > 1.0 > 10 * f_clean[-1, I["q_line_ratio"]]


def test_clip_fraction():
    x = np.r_[np.full(50, 2000.0), np.zeros(450)]
    assert window_features(x, x, adc_full_scale_uv=2000.0)[I["q_clip_frac"]] == pytest.approx(0.1)
