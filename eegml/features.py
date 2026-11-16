"""Per-window features (REQ-FEAT-01..05, REQ-FEAT-08).

Every number here is defined so a C implementation can reproduce it exactly:
  1. take WIN_S seconds of *filtered* samples (uV), subtract the window mean;
  2. multiply by a symmetric Hann window w[n] = 0.5 - 0.5 cos(2 pi n / (N-1));
  3. zero-pad to NFFT and take the real FFT;
  4. band power P_b = sum_{lo <= f_k < hi} |X[k]|^2 / sum_n w[n]^2      (uV^2)
  5. log power  = log10(P_b + EPS); relative power = P_b / P_total;
  6. skew and excess kurtosis are population moments of the demeaned
     filtered window (no Hann weighting), as scipy.stats with bias=True.
Quality metrics use the *unfiltered* window so they see what the filters hide.
"""
import numpy as np

from .config import BANDS, EPS, FS, HOP_S, LINE_BAND_HALF_WIDTH, NFFT, TOTAL_BAND, WIN_S

BAND_NAMES = list(BANDS)
FEATURE_NAMES = (
    [f"logp_{b}" for b in BAND_NAMES]
    + [f"rel_{b}" for b in BAND_NAMES]
    + ["ratio_delta_beta", "ratio_alpha_beta", "ratio_theta_alpha"]
    + ["skew", "kurtosis"]
    + ["q_ptp_uv", "q_line_ratio", "q_clip_frac"]
)


def window_bounds(n_samples: int, fs: float = FS, win_s: float = WIN_S, hop_s: float = HOP_S):
    """Start indices of every full window."""
    win, hop = int(round(win_s * fs)), int(round(hop_s * fs))
    return np.arange(0, n_samples - win + 1, hop), win


def _bin_masks(fs: float, nfft: int):
    f = np.fft.rfftfreq(nfft, 1 / fs)
    masks = {b: (f >= lo) & (f < hi) for b, (lo, hi) in BANDS.items()}
    masks["_total"] = (f >= TOTAL_BAND[0]) & (f < TOTAL_BAND[1])
    return f, masks


def moments(x: np.ndarray):
    """Population skew and excess kurtosis of a 1-D array (bias=True)."""
    d = x - x.mean()
    m2 = np.mean(d ** 2)
    if m2 <= 0:
        return 0.0, 0.0
    return float(np.mean(d ** 3) / m2 ** 1.5), float(np.mean(d ** 4) / m2 ** 2 - 3.0)


def window_features(filt: np.ndarray, raw: np.ndarray | None = None, fs: float = FS,
                    nfft: int = NFFT, line_freq: float = 60.0, adc_full_scale_uv: float | None = None,
                    _cache: dict = {}) -> np.ndarray:
    """Feature vector (FEATURE_NAMES order) for one window."""
    n = len(filt)
    key = (n, fs, nfft)
    if key not in _cache:
        w = np.hanning(n)
        f, masks = _bin_masks(fs, nfft)
        _cache[key] = (w, np.sum(w ** 2), f, masks)
    w, w2, f, masks = _cache[key]

    x = filt - filt.mean()
    spec = np.abs(np.fft.rfft(x * w, nfft)) ** 2 / w2
    p = {b: spec[masks[b]].sum() for b in BAND_NAMES}
    p_tot = spec[masks["_total"]].sum()
    logp = [np.log10(p[b] + EPS) for b in BAND_NAMES]
    rel = [p[b] / p_tot if p_tot > 0 else 0.0 for b in BAND_NAMES]
    ratios = [p["delta"] / (p["beta"] + EPS), p["alpha"] / (p["beta"] + EPS), p["theta"] / (p["alpha"] + EPS)]
    sk, ku = moments(filt)

    r = filt if raw is None else raw
    ptp = float(np.ptp(filt))
    rs = np.abs(np.fft.rfft((r - r.mean()) * w, nfft)) ** 2 / w2
    line = (f >= line_freq - LINE_BAND_HALF_WIDTH) & (f < line_freq + LINE_BAND_HALF_WIDTH)
    lo, hi = TOTAL_BAND
    line_ratio = float(rs[line].sum() / (rs[(f >= lo) & (f < hi)].sum() + EPS)) if line.any() else 0.0
    clip = float(np.mean(np.abs(r) >= 0.98 * adc_full_scale_uv)) if adc_full_scale_uv else 0.0
    return np.array(logp + rel + ratios + [sk, ku, ptp, line_ratio, clip], dtype=float)


def sliding_features(filt: np.ndarray, raw: np.ndarray | None = None, fs: float = FS, **kw):
    """Features for every full window. Returns (starts, matrix[n_windows, n_features])."""
    starts, win = window_bounds(len(filt), fs)
    rows = [window_features(filt[s:s + win], None if raw is None else raw[s:s + win], fs=fs, **kw)
            for s in starts]
    return starts, np.array(rows).reshape(len(starts), len(FEATURE_NAMES))
