"""30 s epoch features for sleep staging (REQ-FEAT-06, REQ-FEAT-07).

An epoch's windows are the full windows that lie entirely inside it: with 2 s
windows and a 1 s hop that is 29 windows per 30 s epoch.
"""
import numpy as np

from .config import EPOCH_S, FS, WIN_S
from .features import FEATURE_NAMES

# Window features summarised by mean and SD across the epoch.
SUMMARISED = [n for n in FEATURE_NAMES if n.startswith(("logp_", "rel_", "skew", "kurtosis"))]
EPOCH_FEATURE_NAMES = (
    [f"{n}_mean" for n in SUMMARISED] + [f"{n}_sd" for n in SUMMARISED]
    + ["q_ptp_uv_max", "q_line_ratio_mean"]
)


def epoch_features(starts: np.ndarray, feats: np.ndarray, epoch_onsets: np.ndarray,
                   fs: float = FS, epoch_s: float = EPOCH_S, win_s: float = WIN_S):
    """Aggregate window features into one row per epoch onset (in samples).

    Returns (matrix[n_epochs, n_epoch_features], n_windows_per_epoch).
    Epochs with no full window get NaN rows.
    """
    idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
    cols = [idx[n] for n in SUMMARISED]
    ep, win = int(round(epoch_s * fs)), int(round(win_s * fs))
    out, counts = [], []
    for e in np.asarray(epoch_onsets, dtype=int):
        m = (starts >= e) & (starts + win <= e + ep)
        counts.append(int(m.sum()))
        if not m.any():
            out.append(np.full(len(EPOCH_FEATURE_NAMES), np.nan)); continue
        f = feats[m]
        out.append(np.r_[f[:, cols].mean(0), f[:, cols].std(0),
                         f[:, idx["q_ptp_uv"]].max(), f[:, idx["q_line_ratio"]].mean()])
    return np.array(out), np.array(counts)
