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

# REQ-FEAT-10, REQ-ML-03: sleep-model input. Each epoch's features are z-scored
# with the session's calibration mean/SD, clipped, then the previous epochs are
# appended: input = [t, t-1, ..., t-SLEEP_NEIGHBOURS].
SLEEP_NEIGHBOURS = 2
SLEEP_INPUT_CLIP = 6.0      # standardised units
SLEEP_SD_FLOOR = 1e-6
# REQ-FEAT-10 (changed 2026-11-21): running per-session standardisation. The
# first SLEEP_WARMUP_EPOCHS epochs (5 min) are buffered and scored together with
# their own mean/SD once the warm-up completes; after that each epoch updates the
# running mean/SD (Welford, population SD) and is then standardised with it.
SLEEP_STANDARDISE = "running"   # or "whole-night" (offline reference only)
SLEEP_WARMUP_EPOCHS = 10

# REQ-HW-02/03, REQ-ACQ-01/02: ADS1115 front end. Differential A0 (Pill OUT)
# against the 1.65 V divider on A1 at +-2.048 V; fallback single-ended A0 at
# +-4.096 V. 250 SPS continuous, paced by ALERT/RDY.
ADC_I2C_ADDR = 0x48
ADC_I2C_HZ = 400_000
ADC_SPS = 250
ADC_PGA_FS_V = 2.048
ADC_FALLBACK_PGA_FS_V = 4.096
# Pill gain (electrode uV -> Pill output uV). PLACEHOLDER: the vendor value was not
# confirmed (2026-11-22); set it from the bench calibration with a known 10 Hz test
# signal (REQ-ACQ-01). Staging is insensitive to it (running standardisation removes a
# constant log-power offset); absolute uV readouts and clip thresholds are not.
PILL_GAIN = 1000.0
