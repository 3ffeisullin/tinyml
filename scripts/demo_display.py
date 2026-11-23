"""Laptop demo display (task 7d): what the XIAO is doing, live, in one window.

Three views:

  replay  The board stages a Sleep-EDF night streamed to it over USB (same path as
          scripts/replay_night.py). The board's hypnogram builds up epoch by epoch next to
          the sleep experts' hypnogram, with relative band power across the night and
          running scores: board = PC reference, agreement with the experts, board time.
          The default subject, 20, is a held-out night (not in the model's training set).
          --port none plays the PC reference instead (no board): a rehearsal and fallback.

  live    The board's own live path (task 7a): log band power and relative alpha over the
          last 2 minutes, from its "W" lines; stages after the 10-epoch warm-up (5 min);
          sample rate and error counters. --source fake needs no sensor; adc / adc-se read
          the ADS1115 once it's wired (docs/bringup.md). A signal-quality banner (eegml/quality.py)
          says when the signal is bad and why (electrode off, mains hum, movement, flat line,
          no data); bad stretches are tinted red, and epochs staged mostly from bad signal
          are hatched in the hypnogram.

  oura    Everything the Oura ring recorded for one night and day (task 5): Oura's 30 s
          hypnogram, heart rate and HRV through the night, deep sleep per night, and every
          score and value the app has pulled (sleep, readiness, activity, stress, heart
          health). Reads data/oura/live (run `python -m hub.oura_app pull` first);
          --sandbox shows Oura's sample data instead.

    .\\venv\\Scripts\\python.exe scripts\\demo_display.py replay --port COM5
    .\\venv\\Scripts\\python.exe scripts\\demo_display.py replay --port none
    .\\venv\\Scripts\\python.exe scripts\\demo_display.py live --source fake --port COM5

--save PATH writes a PNG of the window when the replay ends (or after --seconds in live
mode); --headless runs without a window (for slides and tests).

SAFETY (REQ-SAFE-01..03): live mode with electrodes on a person only with the laptop on
battery (charger unplugged) or through the USB isolator.
"""
import argparse
import textwrap
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

BANDS = ["delta", "theta", "alpha", "sigma", "beta", "gamma"]
STAGES = ["W", "N1", "N2", "N3", "REM"]              # model output order (eegml.sleep_edf.STAGE_NAMES)
STAGE_Y = {0: 4, 4: 3, 1: 2, 2: 1, 3: 0}              # hypnogram rows, top to bottom: W, REM, N1, N2, N3
STAGE_TICKS = ([4, 3, 2, 1, 0], ["Wake", "REM", "N1", "N2", "N3"])
EPOCH_S = 30.0
WARMUP = 10

# Reference palette (dataviz skill, light mode): categorical slots 1-6 in fixed order for the bands.
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
BAND_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
BOARD, EXPERTS = "#2a78d6", "#9a9994"
ALPHA_COLOUR = BAND_COLOURS[2]
# Status palette (dataviz reference; reserved for state, always paired with an icon and a word).
STATUS_STYLE = {"ok": ("✓", "Signal OK", "#0ca30c", "#ffffff"),
                "warn": ("⚠", "Check signal", "#fab219", "#0b0b0b"),
                "bad": ("✕", "Bad signal", "#d03b3b", "#ffffff"),
                "none": ("…", "Waiting for data", "#e6e5e1", "#52514e")}
CRITICAL = STATUS_STYLE["bad"][2]


# ---------------------------------------------------------------- parsing
def parse(line: str):
    """One line from firmware/eeg_node -> an event tuple, or None for lines the display ignores."""
    parts = line.split()
    if not parts:
        return None
    tag = parts[0]
    try:
        if tag == "W" and len(parts) == 12:
            v = [float(x) for x in parts[1:]]
            return ("win", v[0], v[1:7], v[7], v[8], v[9], v[10])  # t_end, logp[6], rel_alpha, ptp, line, clip
        if tag == "OUT" and len(parts) == 8:
            return ("out", int(parts[1]), STAGES.index(parts[2]))
        if tag == "FEAT" and len(parts) == 33:
            return ("feat", int(parts[1]), np.array([float(x) for x in parts[3:]]))
        if tag == "STAT":  # "STAT samples 83751 rate 250.00 Hz missed 0 ...": each key is followed by its value
            keys = ("samples", "rate", "missed", "i2c_errors", "queue_full")
            return ("stat", {k: float(parts[i + 1]) for i, k in enumerate(parts[:-1]) if k in keys})
    except ValueError:
        return None
    if tag == "FAKE" or tag == "ERR" or (tag == "OK" and len(parts) > 1 and parts[1] == "LIVE"):
        return ("msg", line)
    if tag == "ADC":
        return ("msg", line)
    return None


# ---------------------------------------------------------------- sources (background threads)
def replay_source(q: queue.Queue, stop: threading.Event, subject: int, max_epochs: int, port: str,
                  epoch_delay: float):
    try:
        import serial
        import replay_night as rn
        q.put(("msg", f"Loading Sleep-EDF subject {subject} and computing the PC reference..."))
        seg32, labels = rn.prepare_night(subject, max_epochs)
        n = len(labels)
        ref_feats, _, ref_stage = rn.python_reference(seg32, n)
        board = port.lower() != "none"
        q.put(("night", {"subject": subject, "labels": labels, "ref_stage": ref_stage, "board": board}))
        if not board:
            for e in range(n):
                if stop.is_set():
                    return
                q.put(("feat", e, ref_feats[e]))
                q.put(("out", e, int(ref_stage[e])))
                q.put(("ack", e, None))
                time.sleep(epoch_delay)
            q.put(("done", None))
            return
        with serial.Serial(port, 115200, timeout=1) as p:
            q.put(("msg", f"Resetting the XIAO on {port} (self-tests)..."))
            rn.open_board(p, rn.LINE_FREQ, [])
            q.put(("msg", f"board on {port}"))
            for e in range(n):
                if stop.is_set():
                    return
                t0 = time.time()
                lines, us = rn.send_epoch(p, seg32[e * rn.EPOCH_N:(e + 1) * rn.EPOCH_N])
                for line in lines:
                    ev = parse(line)
                    if ev and ev[0] in ("feat", "out"):
                        q.put(ev)
                q.put(("ack", e, us))
                time.sleep(max(0.0, epoch_delay - (time.time() - t0)))
            for line in rn.end_session(p):
                ev = parse(line)
                if ev and ev[0] == "out":
                    q.put(ev)
        q.put(("done", None))
    except Exception as exc:  # shown in the window rather than lost in a thread
        q.put(("error", f"{type(exc).__name__}: {exc}"))


LIVE_COMMANDS = {"fake": "LIVE FAKE", "adc": "LIVE ADC", "adc-se": "LIVE ADC SE"}


def live_source(q: queue.Queue, stop: threading.Event, port: str, source: str):
    try:
        import serial
        with serial.Serial(port, 115200, timeout=0.5) as p:
            q.put(("msg", f"Resetting the XIAO on {port} (self-tests)..."))
            p.dtr = False; p.rts = True; time.sleep(0.1); p.rts = False
            p.close(); time.sleep(1.5); p.open()
            end = time.time() + 30
            while True:
                if time.time() > end:
                    raise TimeoutError("the board did not print READY")
                line = p.readline().decode(errors="replace").strip()
                ev = parse(line)
                if ev and ev[0] == "msg":
                    q.put(ev)
                if line == "READY":
                    break
            p.write((LIVE_COMMANDS[source] + "\n").encode())
            q.put(("started", time.time()))
            while not stop.is_set():
                line = p.readline().decode(errors="replace").strip()
                ev = parse(line) if line else None
                if ev:
                    q.put(ev)
            p.write(b"STOP\n")
    except Exception as exc:
        q.put(("error", f"{type(exc).__name__}: {exc}"))


# ---------------------------------------------------------------- views
def style_axes(ax, ylabel=""):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK2, fontsize=9)


def hypnogram_axes(ax, title):
    style_axes(ax)
    ax.set_yticks(*STAGE_TICKS)
    ax.set_ylim(-0.5, 4.5)
    ax.set_title(title, loc="left", color=INK, fontsize=11)


class TextPanel:
    """Right-hand column: label/value rows, values large."""

    def __init__(self, ax, rows):
        ax.axis("off")
        self.vals = {}
        y = 0.98
        for key, label, big in rows:
            ax.text(0, y, label, color=INK2, fontsize=10, va="top", transform=ax.transAxes)
            self.vals[key] = ax.text(0, y - 0.045, "–", color=INK, fontsize=20 if big else 13,
                                     va="top", transform=ax.transAxes)
            y -= 0.13 if big else 0.105
        self.note = ax.text(0, 0.0, "", color=INK2, fontsize=9.5, va="bottom", transform=ax.transAxes)

    def set_note(self, text, width=44):
        self.note.set_text("\n".join(textwrap.fill(par, width) for par in text.split("\n")) if text else "")

    def set(self, key, text):
        self.vals[key].set_text(text)


class ReplayView:
    def __init__(self, fig):
        gs = fig.add_gridspec(3, 2, width_ratios=[3.3, 1], height_ratios=[1, 1, 1.15],
                              left=0.07, right=0.98, top=0.84, bottom=0.12, hspace=0.5, wspace=0.1)
        self.fig = fig
        self.ax_exp = fig.add_subplot(gs[0, 0])
        self.ax_brd = fig.add_subplot(gs[1, 0], sharex=self.ax_exp)
        self.ax_band = fig.add_subplot(gs[2, 0], sharex=self.ax_exp)
        hypnogram_axes(self.ax_exp, "Sleep experts' hypnogram (scored by hand)")
        hypnogram_axes(self.ax_brd, "XIAO: stages computed on the board")
        style_axes(self.ax_band, "share of band power")
        self.ax_band.set_title("Relative band power, per 30 s epoch (from the board)", loc="left",
                               color=INK, fontsize=11)
        self.ax_band.set_xlabel("hours into the night", color=INK2, fontsize=9)
        self.ax_band.set_ylim(0, 1)
        self.exp_line, = self.ax_exp.plot([], [], color=EXPERTS, lw=2, drawstyle="steps-post")
        self.ghost, = self.ax_brd.plot([], [], color=EXPERTS, lw=1.5, alpha=0.45, drawstyle="steps-post",
                                       label="experts")
        self.brd_line, = self.ax_brd.plot([], [], color=BOARD, lw=2, drawstyle="steps-post", label="XIAO")
        self.brd_legend = self.ax_brd.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), fontsize=9,
                                             frameon=False, ncol=2, labelcolor=INK2)
        self.cursors = [ax.axvline(0, color=MUTED, lw=1, ls=":") for ax in (self.ax_exp, self.ax_brd, self.ax_band)]
        self.panel = TextPanel(fig.add_subplot(gs[:, 1]), [
            ("epoch", "Epoch", True), ("agree_ref", "XIAO = PC reference", True),
            ("agree_exp", "Agreement with the sleep experts", True), ("us", "Board time per 30 s epoch", False),
            ("model", "Model on the board", False)])
        self.panel.set("model", "int8 neural net, 6.3 KB")
        self.title = fig.text(0.07, 0.95, "XIAO sleep staging: replayed night", fontsize=16, color=INK)
        self.sub = fig.text(0.07, 0.915, "", fontsize=10, color=INK2)
        self.band_polys = []
        self.band_legend = False
        self.night = None
        self.base = ""
        self.n = 0
        self.stage = self.feats = None
        self.acked = -1
        self.us = []
        self.finished = False

    def on(self, ev):
        kind = ev[0]
        if kind == "msg":
            self.sub.set_text(self.base + ("   ·   " if self.base else "") + ev[1])
        elif kind == "error":
            self.sub.set_text("Error: " + ev[1])
            self.sub.set_color("#e34948")
        elif kind == "night":
            d = self.night = ev[1]
            self.n = len(d["labels"])
            self.stage = np.full(self.n, -1)
            self.feats = np.full((self.n, 6), np.nan)
            hours = self.n * EPOCH_S / 3600
            for ax in (self.ax_exp,):
                ax.set_xlim(0, hours)
            held = "held-out night, not in the model's training set" if d["subject"] >= 20 else \
                "a training-set night"
            src = "streamed to the XIAO over USB" if d["board"] else "PC reference playback (no board connected)"
            self.title.set_text(f"XIAO sleep staging: Sleep-EDF subject {d['subject']}, {hours:.1f} h")
            self.base = f"{held}; {src}"
            self.sub.set_text(self.base)
            if not d["board"]:
                self.ax_brd.set_title("PC reference: stages from the same int8 model", loc="left",
                                      color=INK, fontsize=11)
                self.ax_band.set_title("Relative band power, per 30 s epoch (PC reference)", loc="left",
                                       color=INK, fontsize=11)
                self.brd_line.set_label("PC reference")
                self.brd_legend.remove()
                self.brd_legend = self.ax_brd.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), fontsize=9,
                                                     frameon=False, ncol=2, labelcolor=INK2)
                self.panel.set("agree_ref", "n/a (no board)")
                self.panel.set("us", "n/a")
        elif kind == "feat" and self.feats is not None:
            rel = ev[2][6:12]
            self.feats[ev[1]] = rel / rel.sum()
        elif kind == "out" and self.stage is not None:
            self.stage[ev[1]] = ev[2]
        elif kind == "ack":
            self.acked = ev[1]
            if ev[2] is not None:
                self.us.append(ev[2])
        elif kind == "done":
            self.finished = True

    def redraw(self):
        if self.night is None or self.acked < 0:
            return
        k = self.acked + 1
        x = np.arange(k + 1) * EPOCH_S / 3600
        lab = self.night["labels"][:k]
        ye = np.array([STAGE_Y[v] if v >= 0 else np.nan for v in lab], float)
        ye = np.append(ye, ye[-1])
        self.exp_line.set_data(x, ye)
        self.ghost.set_data(x, ye)
        done = self.stage[:k] >= 0
        yb = np.array([STAGE_Y[v] if v >= 0 else np.nan for v in self.stage[:k]], float)
        self.brd_line.set_data(x, np.append(yb, yb[-1]))
        for c in self.cursors:
            c.set_xdata([x[-1], x[-1]])
        for p in self.band_polys:
            p.remove()
        f = self.feats[:k]
        ok = ~np.isnan(f[:, 0])
        xs = np.arange(k)[ok] * EPOCH_S / 3600
        self.band_polys = self.ax_band.stackplot(xs, f[ok].T, colors=BAND_COLOURS, labels=BANDS,
                                                 edgecolor=SURFACE, linewidth=0.3) if ok.any() else []
        if self.band_polys and not self.band_legend:
            self.ax_band.legend(loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=6, fontsize=9,
                                frameon=False, labelcolor=INK2)
            self.band_legend = True

        self.panel.set("epoch", f"{k:,} / {self.n:,}   ({k * EPOCH_S / 3600:.1f} h)")
        staged = np.flatnonzero(done)
        if len(staged):
            if self.night["board"]:
                agree = (self.stage[staged] == self.night["ref_stage"][staged]).mean()
                self.panel.set("agree_ref", f"{100 * agree:.1f} % of epochs")
            scored = staged[self.night["labels"][staged] >= 0]
            if len(scored):
                acc = (self.stage[scored] == self.night["labels"][scored]).mean()
                self.panel.set("agree_exp", f"{100 * acc:.1f} %")
        if self.us:
            self.panel.set("us", f"{np.median(self.us) / 1000:.0f} ms (median)")
        if not len(staged) and self.night["board"]:
            self.panel.set_note(f"Warm-up: the board stages its first {WARMUP} epochs once it has seen "
                                     f"{WARMUP} ({k}/{WARMUP}), to normalise to this person.")
        else:
            self.panel.set_note("Agreement with experts on this one night: cross-validated over 20 people "
                                     "the model scores 76.8 % (macro F1 0.707). One forehead channel; "
                                     "REM vs wake is its main confusion." if self.finished else "")


class LiveView:
    WINDOW_S = 120

    def __init__(self, fig, source):
        gs = fig.add_gridspec(3, 2, width_ratios=[3.3, 1], height_ratios=[1.2, 1, 0.9],
                              left=0.07, right=0.98, top=0.84, bottom=0.08, hspace=0.55, wspace=0.1)
        self.ax_pow = fig.add_subplot(gs[0, 0])
        self.ax_alpha = fig.add_subplot(gs[1, 0], sharex=self.ax_pow)
        self.ax_hyp = fig.add_subplot(gs[2, 0])
        style_axes(self.ax_pow, "log10 power (µV²)")
        self.ax_pow.set_title("Band power, each 1 s window (last 2 minutes)", loc="left", color=INK, fontsize=11)
        style_axes(self.ax_alpha, "fraction of power")
        self.ax_alpha.set_title("Relative alpha (8.5–11.5 Hz): rises with eyes closed", loc="left",
                                color=INK, fontsize=11)
        self.ax_alpha.set_xlabel("seconds (0 = now)", color=INK2, fontsize=9)
        self.ax_pow.set_xlim(-self.WINDOW_S, 0)
        self.ax_alpha.set_ylim(0, 1)
        hypnogram_axes(self.ax_hyp, f"Stages from the board (first stage after {WARMUP} epochs = 5 min)")
        self.ax_hyp.set_xlabel("minutes since start", color=INK2, fontsize=9)
        self.ax_hyp.set_xlim(0, 30)
        self.pow_lines = [self.ax_pow.plot([], [], color=c, lw=2, label=b)[0] for b, c in zip(BANDS, BAND_COLOURS)]
        self.ax_pow.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=6, fontsize=9, frameon=False,
                           labelcolor=INK2, handlelength=1.2, columnspacing=1.0)
        self.alpha_line, = self.ax_alpha.plot([], [], color=ALPHA_COLOUR, lw=2)
        self.hyp_line, = self.ax_hyp.plot([], [], color=BOARD, lw=2, drawstyle="steps-post")
        src = {"fake": "fake ADC (250 Hz timer replaying a test signal; no sensor)",
               "adc": "ADS1115, differential A0–A1", "adc-se": "ADS1115, single-ended A0"}[source]
        fig.text(0.07, 0.95, "XIAO live EEG", fontsize=16, color=INK)
        self.sub = fig.text(0.07, 0.915, f"Source: {src}", fontsize=10, color=INK2)
        self.panel = TextPanel(fig.add_subplot(gs[:, 1]), [
            ("alpha", "Relative alpha now", True), ("rate", "Sample rate", False),
            ("errors", "Missed samples / I2C errors / overflows", False), ("ptp", "Peak-to-peak (1 s)", False),
            ("line", "Mains (60 Hz) ratio", False), ("clip", "Clipped samples", False)])
        self.parity = ""
        self.source = source
        from eegml.quality import QualityTracker
        self.quality = QualityTracker()
        self.banner = fig.text(0.98, 0.955, "", ha="right", va="center", fontsize=15, weight="bold",
                               bbox=dict(boxstyle="round,pad=0.45", lw=0))
        self.reason = fig.text(0.98, 0.905, "", ha="right", va="center", fontsize=10.5, color=INK)
        self._shades = []
        self.win_bad = deque(maxlen=self.WINDOW_S * 2)
        self.win = deque(maxlen=self.WINDOW_S * 2)
        self.stages = {}
        self.started = None
        self.last_t = 0.0

    def on(self, ev):
        kind = ev[0]
        if kind == "win":
            self.win.append(ev[1:])
            self.last_t = ev[1]
            wq = self.quality.add_window(ev[1], ev[4], ev[5], ev[6], time.time())
            self.win_bad.append(wq.level == "bad")
        elif kind == "out":
            self.stages[ev[1]] = ev[2]
        elif kind == "stat":
            s = ev[1]
            self.panel.set("rate", f"{s.get('rate', 0):.2f} Hz")
            if "missed" in s:
                self.quality.add_stat(s["missed"], time.time())
            self.panel.set("errors", f"{s.get('missed', 0):.0f} / {s.get('i2c_errors', 0):.0f} / "
                                     f"{s.get('queue_full', 0):.0f}")
        elif kind == "started":
            self.started = ev[1]
        elif kind == "msg":
            if ev[1].startswith("FAKE PARITY"):
                self.parity = ("Fake-source check PASS: live windows match the PC reference"
                               if "PASS" in ev[1] else ev[1])
            elif ev[1].startswith("ERR") or (ev[1].startswith("ADC") and self.source != "fake"):
                self.sub.set_text(self.sub.get_text().split("   |")[0] + "   |   " + ev[1])
        elif kind == "error":
            self.sub.set_text("Error: " + ev[1])
            self.sub.set_color("#e34948")

    def update_quality(self, now=None):
        level, msg = self.quality.status(time.time() if now is None else now)
        icon, word, bg, fg = STATUS_STYLE[level]
        self.banner.set_text(f"{icon}  {word}")
        self.banner.set_color(fg)
        self.banner.get_bbox_patch().set_facecolor(bg)
        if self.source == "fake" and "mains hum" in msg.lower():
            msg += "  (expected: the fake test signal carries 60 Hz hum on purpose)"
        self.reason.set_text("" if level == "ok" else msg)
        for s in self._shades:
            s.remove()
        self._shades = []
        if self.win:
            t = np.array([r[0] for r in self.win]) - self.last_t
            bad = np.array(self.win_bad, dtype=bool)
            if bad.any():
                for ax in (self.ax_pow, self.ax_alpha):
                    self._shades.append(ax.fill_between(t, 0, 1, where=bad, step="mid", color=CRITICAL, alpha=0.13,
                                                        lw=0, transform=ax.get_xaxis_transform()))
        bad_ep = self.quality.bad_epochs()
        for e in bad_ep:
            self._shades.append(self.ax_hyp.axvspan(e * EPOCH_S / 60, (e + 1) * EPOCH_S / 60, color=CRITICAL,
                                                    alpha=0.12, hatch="///", lw=0))
        self.ax_hyp.set_title(f"Stages from the board (first stage after {WARMUP} epochs = 5 min)"
                              + ("   ·   hatched = staged from bad signal, unreliable" if bad_ep else ""),
                              loc="left", color=INK, fontsize=11)
        return level

    def redraw(self):
        self.update_quality()
        if not self.win:
            return
        w = np.array([[r[0], *r[1], r[2], r[3], r[4], r[5]] for r in self.win])
        t = w[:, 0] - self.last_t
        for i, ln in enumerate(self.pow_lines):
            ln.set_data(t, w[:, 1 + i])
        lo, hi = np.nanmin(w[:, 1:7]), np.nanmax(w[:, 1:7])
        self.ax_pow.set_ylim(lo - 0.3, hi + 0.3)
        self.alpha_line.set_data(t, w[:, 7])
        cur = w[-1]
        self.panel.set("alpha", f"{cur[7]:.2f}")
        from eegml.quality import classify_window
        mark = {"ok": "", "warn": "  ⚠", "bad": "  ✕"}       # icon beside the value; text stays ink
        self.panel.set("ptp", f"{cur[8]:.0f} µV" + mark[classify_window(cur[8], 0.0, 0.0).level])
        self.panel.set("line", f"{cur[9]:.2f}" + mark[classify_window(50.0, cur[9], 0.0).level])
        self.panel.set("clip", f"{100 * cur[10]:.1f} %" + mark[classify_window(50.0, 0.0, cur[10]).level])
        if self.stages:
            ts = sorted(self.stages)
            x = np.array(ts + [ts[-1] + 1]) * EPOCH_S / 60
            y = [STAGE_Y[self.stages[k]] for k in ts]
            self.hyp_line.set_data(x, y + [y[-1]])
            self.ax_hyp.set_xlim(0, max(30, x[-1] + 2))
            warm = ""
        else:
            left = max(0, WARMUP * EPOCH_S - self.last_t)
            warm = f"Warm-up: first stage in about {int(left // 60)}:{int(left % 60):02d} min"
        self.panel.set_note("\n".join(s for s in (warm, self.parity) if s))


# ---------------------------------------------------------------- main
# ---------------------------------------------------------------- Oura view
def mdates_num(t):
    import matplotlib.dates as mdates
    return mdates.date2num(t)


OURA_ROWS = {"awake": 3, "REM": 2, "light": 1, "deep": 0}
OURA_TICKS = ([3, 2, 1, 0], ["Awake", "REM", "Light", "Deep"])


class OuraView:
    """Static page: one Oura day. Single-series charts share one accent; text wears ink tokens."""

    finished = True

    def __init__(self, fig, v, source):
        from datetime import timedelta, timezone
        import matplotlib.dates as mdates
        from hub.oura_app.report import day_lines
        self.fig = fig
        off = (v["night"] or {}).get("utc_offset", "+00:00")
        tz = timezone(timedelta(hours=int(off[:3]), minutes=int(off[0] + off[4:])))
        gs = fig.add_gridspec(4, 3, width_ratios=[3.0, 1.05, 1.05], height_ratios=[1.15, 1, 1, 0.9],
                              left=0.06, right=0.99, top=0.85, bottom=0.07, hspace=0.8, wspace=0.12)
        fig.text(0.06, 0.955, f"Oura ring · night ending {v['day']}", color=INK, fontsize=16, weight="bold")
        fig.text(0.06, 0.92, f"{source}. Context only: Oura stages sleep from heart rate, HRV, movement and "
                 "temperature, not EEG; light = N1 + N2.", color=INK2, fontsize=9.5)
        fmt = mdates.DateFormatter("%H:%M", tz=tz)

        ax = fig.add_subplot(gs[0, 0])
        style_axes(ax)
        ax.set_title("Sleep stages (Oura, 30 s)", loc="left", color=INK, fontsize=11)
        ax.set_yticks(*OURA_TICKS)
        ax.set_ylim(-0.5, 3.5)
        hyp = v["hypnogram"]
        if hyp:
            ts = [h[0] for h in hyp] + [hyp[-1][0] + (hyp[1][0] - hyp[0][0] if len(hyp) > 1 else timedelta(0))]
            ys = [OURA_ROWS.get(s, 3) for _, s in hyp]
            ax.step(ts, ys + ys[-1:], where="post", color=BOARD, lw=1.6)
            for (t0, s), t1 in zip(hyp, ts[1:]):
                if s == "deep":
                    ax.axvspan(t0, t1, ymin=0, ymax=0.25, color=BOARD, alpha=0.18, lw=0)
        ax.xaxis.set_major_formatter(fmt)
        self._series(fig.add_subplot(gs[1, 0], sharex=ax), v["hr"], "Heart rate through the night", "bpm", fmt)
        self._series(fig.add_subplot(gs[2, 0], sharex=ax), v["hrv"], "HRV through the night (RMSSD)", "ms", fmt)

        axd = fig.add_subplot(gs[3, 0])
        style_axes(axd, "min")
        axd.set_title("Deep sleep per night (Oura)", loc="left", color=INK, fontsize=11)
        tr = v["trend"][-30:]
        if tr:
            x = np.arange(len(tr))
            vals = [r["deep_min"] for r in tr]
            axd.bar(x, vals, width=0.6, color=[BOARD if r["day"] == v["day"] else "#9ec3ec" for r in tr])
            axd.set_xticks(x, [r["day"][5:] for r in tr], fontsize=8)
            for xi, val in zip(x, vals):
                axd.text(xi, val, f"{val:.0f}", ha="center", va="bottom", color=INK2, fontsize=8)
            axd.set_ylim(0, max(vals) * 1.3 + 1)
            axd.set_xlim(-0.6, max(len(tr), 14) - 0.4)          # keep bars thin when there are few nights

        rows = day_lines(v)
        cut = next((i for i, (lab, _) in enumerate(rows) if lab == "Readiness score"), len(rows))
        for col, chunk in ((1, rows[:cut]), (2, rows[cut:])):
            axt = fig.add_subplot(gs[:, col])
            axt.axis("off")
            y = 1.0
            for lab, val in chunk:
                sub = lab.startswith("  ")
                axt.text(0.0, y, lab.strip(), color=MUTED if sub else INK2, fontsize=8.5 if sub else 9.5,
                         va="top", transform=axt.transAxes)
                axt.text(1.0, y, val, color=INK, fontsize=8.5 if sub else 10.5, ha="right", va="top",
                         weight="normal" if sub else "bold", transform=axt.transAxes)
                y -= 0.03 if sub else 0.038
            if not chunk:
                axt.text(0, 1, "not pulled yet", color=MUTED, fontsize=9.5, va="top", transform=axt.transAxes)

    @staticmethod
    def _series(ax, pts, title, unit, fmt):
        style_axes(ax, unit)
        ax.set_title(title, loc="left", color=INK, fontsize=11)
        if pts:
            ts, ys = zip(*pts)
            ax.plot(ts, ys, color=BOARD, lw=2)
            i = int(np.argmin(ys)) if unit == "bpm" else int(np.argmax(ys))
            ax.plot([ts[i]], [ys[i]], "o", ms=7, color=BOARD, mec=SURFACE, mew=2)
            ax.set_title(f"{title}  ·  {'lowest' if unit == 'bpm' else 'highest'} {ys[i]:.0f} {unit} at "
                         f"{fmt(mdates_num(ts[i]))}, mean {np.mean(ys):.0f}", loc="left", color=INK, fontsize=11)
            pad = (max(ys) - min(ys)) * 0.25 + 1
            ax.set_ylim(min(ys) - pad, max(ys) + pad)
        else:
            ax.text(0.5, 0.5, "no data for this night", color=MUTED, ha="center", va="center", transform=ax.transAxes)
        ax.xaxis.set_major_formatter(fmt)

    def on(self, _msg):
        pass

    def redraw(self):
        pass


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("replay", help="board stages a replayed Sleep-EDF night")
    r.add_argument("--subject", type=int, default=20, help="Sleep-EDF SC subject (training used 0-19)")
    r.add_argument("--port", default="COM5", help="serial port, or 'none' to play the PC reference")
    r.add_argument("--max-epochs", type=int, default=0, help="0 = whole night")
    r.add_argument("--epoch-delay", type=float, default=0.0,
                   help="minimum seconds per epoch (the board alone takes ~0.4 s; default 0.25 with --port none)")
    l_ = sub.add_parser("live", help="live band powers from the board")
    l_.add_argument("--source", choices=LIVE_COMMANDS, default="fake")
    l_.add_argument("--port", default="COM5")
    l_.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = until the window closes)")
    o = sub.add_parser("oura", help="everything the Oura ring recorded for one night and day")
    o.add_argument("--day", help="YYYY-MM-DD (default: latest stored night)")
    o.add_argument("--sandbox", action="store_true", help="Oura's sample data instead of the ring's")
    for p in (r, l_, o):
        p.add_argument("--save", type=Path, help="write a PNG at the end")
        p.add_argument("--headless", action="store_true", help="no window (needs --save)")
    a = ap.parse_args()
    if a.headless and not a.save:
        sys.exit("Error: --headless needs --save")

    import matplotlib
    if a.headless:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

    fig = plt.figure(figsize=(14, 7.8), facecolor=SURFACE)
    try:
        fig.canvas.manager.set_window_title("XIAO EEG demo")
    except AttributeError:
        pass
    if a.mode == "oura":
        from hub.oura_app.config import DATA_DIR
        from hub.oura_app.data import LocalStore, day_view
        v = day_view(LocalStore(DATA_DIR / ("sandbox" if a.sandbox else "live")), a.day)
        if not v["day"]:
            sys.exit("No Oura nights stored: run `python -m hub.oura_app pull` first.")
        OuraView(fig, v, "Oura sandbox (sample data)" if a.sandbox else "Farid's ring, via the Oura API v2")
        if a.save:
            a.save.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(a.save, dpi=110, facecolor=SURFACE)
            print(f"saved {a.save}")
        if not a.headless:
            plt.show()
        return
    q, stop = queue.Queue(), threading.Event()
    if a.mode == "replay":
        view = ReplayView(fig)
        delay = a.epoch_delay if a.epoch_delay > 0 or a.port.lower() != "none" else 0.25
        if a.headless:
            delay = 0.0
        th = threading.Thread(target=replay_source, args=(q, stop, a.subject, a.max_epochs, a.port, delay), daemon=True)
    else:
        view = LiveView(fig, a.source)
        th = threading.Thread(target=live_source, args=(q, stop, a.port, a.source), daemon=True)
    th.start()
    t_start = time.time()
    state = {"saved": False}

    def finished():
        if a.mode == "replay":
            return view.finished or (not th.is_alive() and q.empty())
        return (a.seconds > 0 and time.time() - t_start >= a.seconds) or not th.is_alive()

    def step(_frame=None):
        for _ in range(5000):
            try:
                view.on(q.get_nowait())
            except queue.Empty:
                break
        view.redraw()
        if finished() and not state["saved"]:
            stop.set()
            if a.save:
                a.save.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(a.save, dpi=110, facecolor=SURFACE)
                print(f"saved {a.save}")
            state["saved"] = True
        return []

    if a.headless:
        while not state["saved"]:
            time.sleep(0.2)
            step()
        th.join(timeout=5)
        return
    from matplotlib.animation import FuncAnimation
    anim = FuncAnimation(fig, step, interval=250, cache_frame_data=False)  # noqa: F841 (keep a reference)
    fig.canvas.mpl_connect("close_event", lambda _e: stop.set())
    plt.show()
    stop.set()
    th.join(timeout=3)


if __name__ == "__main__":
    main()
