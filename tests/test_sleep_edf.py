"""REQ-ML-01: Sleep-EDF path, run on a synthetic night (no download needed)."""
import numpy as np

from eegml.sleep_edf import STAGE_NAMES, scored_epochs, subject_features


def synthetic_night(fs=100.0):
    # 2 h wake, 1 h N2 (spindles + slow), 1 h N3 (big delta), 2 h wake
    plan = [("Sleep stage W", 7200), ("Sleep stage 2", 3600), ("Sleep stage 3", 3600), ("Sleep stage W", 7200)]
    rng = np.random.default_rng(0)
    parts, anns, t0 = [], [], 0.0
    for desc, dur in plan:
        t = np.arange(int(dur * fs)) / fs
        x = 5 * rng.standard_normal(len(t))
        if desc == "Sleep stage W":
            x += 15 * np.sin(2 * np.pi * 10 * t)
        elif desc == "Sleep stage 2":
            x += 10 * np.sin(2 * np.pi * 1.5 * t) + 8 * np.sin(2 * np.pi * 13 * t)
        else:
            x += 60 * np.sin(2 * np.pi * 1.0 * t)
        parts.append(x); anns.append({"onset": t0, "duration": dur, "description": desc}); t0 += dur
    anns.append({"onset": t0, "duration": 30, "description": "Sleep stage ?"})
    return np.concatenate(parts), fs, anns


def test_wake_trimmed_to_30_min_each_side():
    _, _, anns = synthetic_night()
    on, y = scored_epochs(anns)
    assert (y == 0).sum() == 2 * 60 and (y == 2).sum() == 120 and (y == 3).sum() == 120


def test_subject_features_separate_stages():
    x, fs, anns = synthetic_night()
    ours, mne_f, y = subject_features(x, fs, anns)
    assert len(ours) == len(mne_f) == len(y) > 300 and len(STAGE_NAMES) == 5
    from eegml.epochs import EPOCH_FEATURE_NAMES
    d = ours[:, EPOCH_FEATURE_NAMES.index("rel_delta_mean")]
    a = ours[:, EPOCH_FEATURE_NAMES.index("rel_alpha_mean")]
    assert d[y == 3].mean() > d[y == 0].mean() and a[y == 0].mean() > a[y == 3].mean()
