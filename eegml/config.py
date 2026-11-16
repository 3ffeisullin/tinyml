"""Single source of truth for the signal-processing parameters.

The firmware (firmware/eeg_node, to come) must use these exact values; tests/
and scripts/export_test_vectors.py check that it does. Requirement IDs refer to
docs/requirements.md.
"""
from dataclasses import dataclass, field

# REQ-ACQ-02: sampling rate on the device.
FS = 250.0

# REQ-FEAT-01: analysis windows.
WIN_S = 2.0            # 500 samples
HOP_S = 1.0            # 250 samples
NFFT = 512             # zero-padded real FFT -> 0.488 Hz bins
EPOCH_S = 30.0         # REQ-FEAT-06: sleep-scoring epoch

# REQ-FEAT-02: frequency bands, Hz, half-open [lo, hi).
# Delta..beta follow the MNE sleep tutorial (and Sleep-EDF practice) so results
# compare directly with its published baseline; sigma covers sleep spindles;
# gamma is kept for awake/artifact work.
BANDS = {
    "delta": (0.5, 4.5),
    "theta": (4.5, 8.5),
    "alpha": (8.5, 11.5),
    "sigma": (11.5, 15.5),
    "beta": (15.5, 30.0),
    "gamma": (30.0, 45.0),
}
TOTAL_BAND = (0.5, 30.0)   # REQ-FEAT-03: denominator for relative power
LINE_BAND_HALF_WIDTH = 2.0  # Hz either side of mains for the line-noise metric
EPS = 1e-6                  # added before log10, power in uV^2


@dataclass(frozen=True)
class FilterSpec:
    """REQ-FEAT-04: causal IIR chain, applied sample by sample in this order."""
    fs: float = FS
    line_freq: float = 60.0          # 50.0 for European recordings (Sleep-EDF)
    notch_q: float = 30.0
    notch_harmonics: tuple = (1, 2)  # 60 and 120 Hz; skipped if >= Nyquist
    hp_hz: float = 0.5
    hp_order: int = 2
    lp_hz: float = 45.0
    lp_order: int = 4
    extra: dict = field(default_factory=dict)
