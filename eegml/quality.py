"""Signal-quality flags from the per-window quality metrics (REQ-FEAT-08 flags; groundwork for REQ-ML-05).

Each 1 s window from the board carries filtered peak-to-peak (uV), the mains-to-EEG power ratio on
the unfiltered window and the fraction of samples near ADC full scale. `classify_window` turns those
into ok / warn / bad with a plain-language reason; `QualityTracker` smooths over the last few windows
(so a single blink never raises the alarm), notices when data stops or samples go missing, and keeps
a per-epoch count so a hypnogram can mark epochs staged from bad signal.

Thresholds live in eegml/config.py (QualitySpec) and are starting values until bring-up.
"""
from collections import Counter, deque
from dataclasses import dataclass

from . import config

OK, WARN, BAD, NONE = "ok", "warn", "bad", "none"
_RANK = {OK: 0, WARN: 1, BAD: 2}


@dataclass(frozen=True)
class WindowQuality:
    level: str
    reasons: tuple = ()          # short phrases, worst first


def classify_window(ptp_uv: float, line_ratio: float, clip_frac: float,
                    q: config.QualitySpec = config.QUALITY) -> WindowQuality:
    found = []                   # (level, phrase)
    if clip_frac > q.clip_bad:
        found.append((BAD, "ADC at its limit: electrode off or lead loose"))
    elif clip_frac > q.clip_warn:
        found.append((WARN, "a few samples at the ADC limit"))
    if ptp_uv < q.flat_ptp_uv:
        found.append((BAD, "flat signal: check the Pill's power and leads"))
    elif ptp_uv > q.high_ptp_bad_uv:
        found.append((BAD, f"very large swings ({ptp_uv:.0f} µV): electrode off or movement"))
    elif ptp_uv > q.high_ptp_warn_uv:
        found.append((WARN, f"large swings ({ptp_uv:.0f} µV): blink or movement"))
    if line_ratio > q.line_bad:
        found.append((BAD, f"mains hum {line_ratio:.1f}× the EEG: electrode loose or not on skin"))
    elif line_ratio > q.line_warn:
        found.append((WARN, f"mains hum rising ({line_ratio:.2f}× the EEG): check electrode contact"))
    if not found:
        return WindowQuality(OK)
    found.sort(key=lambda f: -_RANK[f[0]])
    return WindowQuality(found[0][0], tuple(p for _, p in found))


class QualityTracker:
    """Overall status from recent windows, data freshness and missed samples.

    `now` is the laptop's clock (seconds); window times `t_end` are the board's seconds since start."""

    def __init__(self, q: config.QualitySpec = config.QUALITY, epoch_s: float = config.EPOCH_S):
        self.q, self.epoch_s = q, epoch_s
        self.recent = deque(maxlen=q.persist_windows)
        self.last_wall = None
        self.missed = None
        self.missed_at = None
        self.epochs = {}         # epoch index -> [bad windows, all windows]

    def add_window(self, t_end: float, ptp_uv: float, line_ratio: float, clip_frac: float, now: float) -> WindowQuality:
        wq = classify_window(ptp_uv, line_ratio, clip_frac, self.q)
        self.recent.append(wq)
        self.last_wall = now
        e = self.epochs.setdefault(int(max(t_end - 1e-6, 0) // self.epoch_s), [0, 0])
        e[0] += wq.level == BAD
        e[1] += 1
        return wq

    def add_stat(self, missed: float, now: float):
        if self.missed is not None and missed > self.missed:
            self.missed_at = now
        self.missed = missed

    def bad_epochs(self) -> list[int]:
        return sorted(k for k, (b, n) in self.epochs.items() if n and b / n > self.q.epoch_bad_frac)

    def status(self, now: float) -> tuple[str, str]:
        """(level, message) for the banner."""
        if self.last_wall is None:
            return NONE, "Waiting for data from the board"
        if now - self.last_wall > self.q.stale_s:
            return BAD, f"No data from the board for {now - self.last_wall:.0f} s: check the USB cable"
        bad = [w for w in self.recent if w.level == BAD]
        if len(bad) >= self.q.bad_min:
            ranked = [r for r, _ in Counter(r for w in bad for r in w.reasons[:2]).most_common(2)]
            msg = "; ".join(ranked)
            return BAD, msg[0].upper() + msg[1:]
        latest = next((w for w in reversed(self.recent) if w.level != OK), None)
        if latest is not None:
            return WARN, latest.reasons[0][0].upper() + latest.reasons[0][1:]
        if self.missed_at is not None and now - self.missed_at < self.q.persist_windows:
            return WARN, f"The board missed samples (total {self.missed:.0f})"
        return OK, "Signal OK"
