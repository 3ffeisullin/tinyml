# Brief: task 6, feature parity on the XIAO (2026-11-21, Claude Code on the laptop)

For the Claude cloud session and Farid's review. Branch `feature/int8-sleep-model`, draft PR #3. Follows
`docs/briefs/2026-11-21-int8-sleep-model.md`.

## Result

The device's filter chain and all 20 window features match Python on the reference vectors
(`firmware/test_vectors/feature_vectors_v1.h`) → **REQ-FEAT-09 Done on the device**.
Log: `reports/xiao_feature_parity_2026-11-21.txt`.

| Check | Limit (REQ-FEAT-09) | On the XIAO |
|---|---|---|
| Filtered samples, max error | 1e-3 of full scale | 6.5e-08 |
| Log band powers | ±0.01 | worst 0.0001 of tolerance |
| Other features | 1e-3 relative (+1e-6 absolute floor) | worst 0.4 % of tolerance (skew) |
| Filter cost | — | 17 µs per sample (≈ 4 ms per second at 250 Hz) |
| Window features cost | — | 5.2 ms per window (one per second) |
| Model inference (unchanged) | 50 ms | 224 µs, parity 5/5 |

Signal processing plus the model use about 1 % of one core. Sketch: 384 KB flash (11 %), 53 KB RAM (16 %).

## What was built

| File | What it is |
|---|---|
| `firmware/eeg_node/eeg_features.h` | C++ port of `eegml/filters.py` and `eegml/features.py`: `eeg::BiquadCascade` (transposed direct form II, double) and `eeg::WindowFeatures` (Hann, 512-point radix-2 FFT, bands, ratios, skew/kurtosis, peak-to-peak, mains ratio, clip fraction). Sums in double. |
| `firmware/eeg_node/eeg_config.h` | **Generated** from `eegml/config.py` by `scripts/export_test_vectors.py`: sample rate, window, hop, FFT size, epoch length, EPS, bands, total band, line half-width, and the 60 Hz and 50 Hz filter chains as full-precision doubles. The firmware has no hand-copied constants. |
| `firmware/eeg_node/feature_vectors_v1.h` | Copy of the vectors header next to the sketch (Arduino can't include files from outside the sketch folder); the exporter writes both, and a test keeps them identical. |
| `firmware/eeg_node/eeg_node.ino` | Stage 2: feature parity (features from Python's filtered samples, and from the board's own filter) + the sleep-model bench; PASS/FAIL summaries every 5 s. |
| `tests/test_vectors.py` | 2 new tests: the generated headers are current, the SOS doubles are bit-exact, and every float literal is valid C. 44 tests pass. |

## Found on the way

1. **float32 biquads aren't accurate enough for skew.** float32 coefficients and state gave filtered samples within
   6e-5 of full scale (inside the limit), but skew, which is near zero in some windows, came out at 2.3× its tolerance.
   The 0.5 Hz high-pass poles sit close to the unit circle. Fix: double coefficients and state. The ESP32-S3 does double
   in software, but at 250 Hz that's 17 µs per sample. With float32 input from Python, all features were already exact,
   so the feature code was never the problem.
2. **Invalid C float literals in the v1 vectors header.** The exporter wrote `1f` and `250f`, which don't compile.
   They went unnoticed because nothing compiled the header before. Fixed (`flit()`), with a test.

## Status of the open items

- Farid's G: drive is **Google Drive** (cloud, synced). A live InfluxDB must not sit on a synced drive (risk of
  corruption, as with the email agent's database in OneDrive). Plan: Docker and the database on C: (about 10–15 GB, 252 GB free);
  optional nightly `influx backup` export into a Google Drive folder once Google Drive for desktop is installed.
- Parts: resistors, capacitors and electrodes in hand. The rest (BioAmp EXG Pill, ADS1115, …) is due in about 5 days
  (around 2026-11-26), one day before the demo (2026-11-27).

## Recommended next steps (demo on 2026-11-27)

| # | Task | Needs parts? | Why now |
|---|---|---|---|
| 6b | End to end on the board: raw samples → filters → window features → 30 s epoch summaries (29 windows, mean/SD) → running standardisation (Welford) → [t, t-1, t-2] → int8 model → stage. Feed a Sleep-EDF night (resampled to 250 Hz, 50 Hz chain) through the board over serial or from flash, and check that the stages match Python epoch for epoch. | No | The core of the demo: the board stages a real night on its own. |
| 7a | ADS1115 driver + 250 Hz sampling loop written and compiled now, with a fake-ADC mode for testing. | No (to write) | Leaves only wiring and a check for the 1 day after the parts arrive. |
| 7 | Wire the Pill + ADS1115; live band powers. With electrodes on a person: XIAO on battery, or USB through the isolator, or the laptop on battery (REQ-SAFE). | Yes (around 11-26) | Live signal for the demo (e.g. the alpha rise with eyes closed). |
| 5 | Oura app | No | Only if the demo needs Oura data. |

Fallback if the parts are late: the demo shows the replayed night (6b) with live stage output, plus the
on-device checks (feature parity, model parity, timings).
