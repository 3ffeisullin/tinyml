# Brief: task 7a, acquisition firmware ready before the parts (2026-11-22, Claude Code)

For the Claude cloud session and Farid's review. Branch `feature/int8-sleep-model`, draft PR #3. Follows
`docs/briefs/2026-11-21-end-to-end-replay.md` (task 6b).

## Result

The live path, from sample acquisition on core 0 through processing on core 1 to stages, runs on the XIAO, fed by a
fake ADC (a 250 Hz timer replaying the reference signal through the same task and queue the ADS1115 will use).
Log: `reports/xiao_live_fake_2026-11-22.txt`.

| Check (335 s live session) | Result |
|---|---|
| Samples / measured rate | 83,751 at 250.00 Hz |
| Missed samples, I2C errors, queue overflows, timeouts | 0, 0, 0, 0 |
| First 11 live windows vs Python | PASS, worst 0.4 % of tolerance |
| Epochs, 29 windows each; model stages after the 10-epoch warm-up | yes (stages are meaningless on a 12 s looped test signal) |
| Sketch size | 401 KB flash (11 %), 95 KB RAM (28 %) |

**Not yet proved (needs the parts, due around 2026-11-26):** the I2C reads, the ALERT/RDY interrupt, and the ADS1115's
real rate. Everything after the sample queue is the code already verified on the board.

## Built

| File | What it is |
|---|---|
| `eegml/acquisition.py` | ADS1115 config words from datasheet bit fields (differential A0–A1 ±2.048 V = `0x04A0`; fallback single-ended A0 ±4.096 V = `0x42A0`; 250 SPS, continuous, ALERT/RDY as conversion-ready), LSB sizes (62.5 / 125 µV) and `counts_to_uv`. Tested. |
| `eegml/config.py` | ADC constants and `PILL_GAIN` (**placeholder 1000**, to be set by bench calibration, REQ-ACQ-01), generated into `firmware/eeg_node/eeg_config.h`. |
| `firmware/eeg_node/acquisition.h` | `acq::Ads1115` (probe, configure + read-back check, read) and `acq::Acquisition`: a core-0 task at the highest priority, woken by ALERT/RDY (falling-edge interrupt) or the fake timer, that pushes µV samples into a 1,024-sample queue. Counts missed wake-ups, I2C errors, queue overflows and timeouts (REQ-ACQ-02/03). Pins per REQ-HW-03: SDA GPIO5 (D4), SCL GPIO6 (D5), RDY GPIO2 (D1). |
| `firmware/eeg_node/eeg_node.ino` | Live mode: `LIVE ADC`, `LIVE ADC SE`, `LIVE FAKE`, `STOP`, `STAT`. Prints `W` (1 s band powers, relative alpha, peak-to-peak, mains ratio, clip fraction), `EPOCH`/`OUT` (30 s epochs and stages), `STAT` every 10 s, and `FAKE PARITY` once. Boot reports whether the ADC is found. |
| `firmware/eeg_node/eeg_pipeline.h` | Now computes every 1 s window, including those straddling two epochs (for the live display); only windows fully inside an epoch enter the epoch summary, as before. |
| `scripts/live_log.py` | Laptop side: starts a live mode, saves the lines, summarises rate, errors, band powers and stages. |
| `docs/bringup.md` | Step-by-step checklist for wiring day: safety, wiring table, ADC probe, resting levels, shorted-input noise and rate, 10 Hz test tone and gain calibration, eyes open/closed on a person. |
| Tests | ADS1115 config words and µV conversion; 47 pass. |

## Things to know for wiring day

1. **The ADS1115's internal oscillator is ±10 %.** "250 SPS" may really be 225–275 Hz, and all band edges scale with
   it. `STAT` measures the rate against the XIAO's crystal; if it's off by more than about 1 %, either pace sampling
   from the XIAO (single-shot conversions on a timer) or correct `EEG_FS`. REQ-ACQ-02's 250 SPS can't be assumed.
2. **The Pill's supply.** The vendor docs list 5 V operation; our design runs it at 3.3 V (REQ-HW-01). The
   architecture's open item, "measure the Pill's resting output at 3.3 V", is step 3 of the checklist; the
   single-ended ±4.096 V fallback is one command away (`LIVE ADC SE`).
3. **Gain doesn't affect staging.** A gain error multiplies every sample by a constant, so log powers shift by a
   constant, which the running standardisation removes; relative powers, skew and kurtosis are scale-free.
   Only absolute µV readouts and the clip threshold depend on the gain.
4. **Calibration arithmetic:** with this pipeline's normalisation, a sine of amplitude A gives band power
   P = 256 × A²/2, so A = √(P/128) µV (checked numerically; an earlier draft of the checklist had √(2P)).
5. **REQ-SAFE-02 can't be enforced in firmware yet.** There's no USB VBUS sense pin in the design. Until there is,
   the safety section of `docs/bringup.md` is the control: electrodes on a person only with the XIAO on its LiPo,
   through the USB isolator, or with the laptop on battery.

## Next

| # | Task | Notes |
|---|---|---|
| 7 | Wiring and bring-up per `docs/bringup.md` when the parts arrive (around 2026-11-26) | Measure the real rate; calibrate the gain; eyes open/closed alpha check. |
| Demo | Laptop display: live band powers / relative alpha from `W` lines, and a hypnogram building up from the replayed night (`replay_night.py`) | Fallback needs no parts. |
| Later | VBUS sense pin (REQ-SAFE-02), UTC-aligned epochs (REQ-FEAT-07, needs NTP), MQTT (REQ-IF-01), artifact gate (REQ-ML-05) | |
