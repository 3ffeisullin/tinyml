"""Sleep-EDF (PhysioNet) loading for the single-forehead-channel baseline (REQ-ML-01..03).

Sleep-EDF's 'EEG Fpz-Cz' channel is the closest public match to the headband's
Fp1-mastoid lead. It is recorded at 100 Hz in Europe (50 Hz mains), so it is
resampled to the device rate before the device feature pipeline runs on it.
"""
from fractions import Fraction

import numpy as np
from scipy import signal

from . import filters
from .config import EPOCH_S, FS, FilterSpec
from .epochs import epoch_features
from .features import sliding_features

STAGE_MAP = {"Sleep stage W": 0, "Sleep stage 1": 1, "Sleep stage 2": 2,
             "Sleep stage 3": 3, "Sleep stage 4": 3, "Sleep stage R": 4}
STAGE_NAMES = ["W", "N1", "N2", "N3", "REM"]
# Bands from the MNE tutorial, used only for its reference feature set.
MNE_TUTORIAL_BANDS = [(0.5, 4.5), (4.5, 8.5), (8.5, 11.5), (11.5, 15.5), (15.5, 30.0)]


def scored_epochs(annotations, trim_wake_min: float = 30.0, epoch_s: float = EPOCH_S):
    """(onset_s, label) for every 30 s scored epoch, wake trimmed to +-trim_wake_min around sleep."""
    ep = []
    for a in annotations:
        lab = STAGE_MAP.get(a["description"])
        if lab is None:
            continue
        for k in range(int(round(a["duration"] / epoch_s))):
            ep.append((a["onset"] + k * epoch_s, lab))
    ep = np.array(ep) if ep else np.empty((0, 2))
    sleep = ep[ep[:, 1] != 0, 0] if len(ep) else []
    if len(sleep):
        lo, hi = sleep.min() - trim_wake_min * 60, sleep.max() + trim_wake_min * 60
        ep = ep[(ep[:, 0] >= lo) & (ep[:, 0] <= hi)]
    return ep[:, 0], ep[:, 1].astype(int)


def mne_tutorial_features(x: np.ndarray, fs: float, onsets_s: np.ndarray, epoch_s: float = EPOCH_S):
    """The MNE tutorial's features on one channel: relative multitaper power in 5 bands."""
    from mne.time_frequency import psd_array_multitaper
    n = int(round(epoch_s * fs))
    segs = np.stack([x[int(round(o * fs)):int(round(o * fs)) + n] for o in onsets_s])
    psd, f = psd_array_multitaper(segs, fs, fmin=0.5, fmax=30.0, verbose=False)
    psd /= psd.sum(-1, keepdims=True)
    return np.stack([psd[:, (f >= lo) & (f < hi)].mean(-1) for lo, hi in MNE_TUTORIAL_BANDS], axis=1)


def subject_features(x_uv: np.ndarray, fs_in: float, annotations, line_freq: float = 50.0,
                     trim_wake_min: float = 30.0):
    """Device features and MNE-tutorial features for one recording.

    x_uv: the Fpz-Cz signal in microvolts at its native rate; annotations: iterable of
    dicts with onset (s from the first sample), duration and description.
    Returns ours[n, k], mne[n, 5], labels[n].
    """
    onsets, y = scored_epochs(annotations, trim_wake_min)
    keep = onsets + EPOCH_S <= len(x_uv) / fs_in
    onsets, y = onsets[keep], y[keep]
    if not len(onsets):
        return np.empty((0, 0)), np.empty((0, 5)), y
    # Device path: start at the first kept epoch so the filter settles in wake.
    start = int(onsets.min() * fs_in)
    seg = x_uv[start:int(np.ceil((onsets.max() + EPOCH_S) * fs_in))]
    r = Fraction(FS / fs_in).limit_denominator(100)
    seg250 = signal.resample_poly(seg, r.numerator, r.denominator)
    filt = filters.apply(seg250, FilterSpec(line_freq=line_freq))
    starts, wf = sliding_features(filt, seg250, line_freq=line_freq)
    ours, counts = epoch_features(starts, wf, np.round((onsets - start / fs_in) * FS).astype(int))
    theirs = mne_tutorial_features(x_uv, fs_in, onsets)
    ok = ~np.isnan(ours).any(1)
    return ours[ok], theirs[ok], y[ok]


class DownloadError(RuntimeError):
    """A Sleep-EDF night could not be fetched (missing upstream, network, certificate)."""


def find_channel(ch_names, channel: str) -> str:
    """Return the channel's name as MNE stored it.

    With infer_types=True MNE strips the type prefix ("EEG Fpz-Cz" -> "Fpz-Cz").
    Raises ValueError naming the available channels if neither form is present,
    so a wrong channel stops the run instead of skipping every subject.
    """
    for name in (channel, channel.split(" ", 1)[-1]):
        if name in ch_names:
            return name
    raise ValueError(f"channel {channel!r} not found; available: {list(ch_names)}")


def load_subject(subject: int, recording: int = 1, channel: str = "EEG Fpz-Cz"):
    """Download (first time) and read one Sleep-EDF night. Returns x_uv, fs, annotations.

    Only download problems raise DownloadError (the baseline skips those subjects);
    anything else, such as a missing channel, propagates and stops the run.
    """
    import warnings

    import mne
    try:
        psg, hyp = mne.datasets.sleep_physionet.age.fetch_data(
            subjects=[subject], recording=[recording], on_missing="raise", verbose=False)[0]
    except Exception as e:  # network, certificate, or night missing upstream
        raise DownloadError(f"subject {subject}: {e.__class__.__name__}: {e}") from e
    with warnings.catch_warnings():
        # Sleep-EDF headers mix filter settings across channel types; MNE warns on every file.
        warnings.filterwarnings("ignore", message=".*(highpass|lowpass|Highpass|Lowpass).*", category=RuntimeWarning)
        raw = mne.io.read_raw_edf(psg, stim_channel="Event marker", infer_types=True,
                                  preload=True, verbose=False)
    raw.set_annotations(mne.read_annotations(hyp), emit_warning=False)
    x = raw.get_data(picks=[find_channel(raw.ch_names, channel)])[0] * 1e6
    t0 = raw.first_time
    anns = [{"onset": a["onset"] - t0, "duration": a["duration"], "description": a["description"]}
            for a in raw.annotations]
    return x, raw.info["sfreq"], anns


def cached_night(subject: int = 0, recording: int = 1):
    """(psg, hypnogram) paths if this night is already in the MNE data folder, else None.

    Never downloads. Sleep-EDF cassette files are named SC4<subject:02d><recording>...
    """
    from pathlib import Path

    import mne
    root = Path(mne.get_config("MNE_DATA") or Path.home() / "mne_data") / "physionet-sleep-data"
    stem = f"SC4{subject:02d}{recording}"
    psg = sorted(root.glob(f"{stem}*-PSG.edf"))
    hyp = sorted(root.glob(f"{stem}*-Hypnogram.edf"))
    return (str(psg[0]), str(hyp[0])) if psg and hyp else None
