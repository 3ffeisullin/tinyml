"""Causal IIR filter chain (REQ-FEAT-04).

Implemented as second-order sections so the firmware can copy the coefficients
into ESP-DSP biquads one-to-one. Zero initial state, like the device at boot.
"""
import numpy as np
from scipy import signal

from .config import FilterSpec


def design_sos(spec: FilterSpec = FilterSpec()) -> np.ndarray:
    """Return the full chain as an (n_sections, 6) SOS array."""
    nyq = spec.fs / 2
    sections = []
    for h in spec.notch_harmonics:
        f0 = spec.line_freq * h
        if f0 < nyq:
            b, a = signal.iirnotch(f0, spec.notch_q, fs=spec.fs)
            sections.append(signal.tf2sos(b, a))
    sections.append(signal.butter(spec.hp_order, spec.hp_hz, "highpass", fs=spec.fs, output="sos"))
    if spec.lp_hz < nyq:
        sections.append(signal.butter(spec.lp_order, spec.lp_hz, "lowpass", fs=spec.fs, output="sos"))
    return np.vstack(sections)


def apply(x: np.ndarray, spec: FilterSpec = FilterSpec(), sos: np.ndarray | None = None) -> np.ndarray:
    """Filter a 1-D signal causally from a zero state."""
    sos = design_sos(spec) if sos is None else sos
    return signal.sosfilt(sos, np.asarray(x, dtype=float))
