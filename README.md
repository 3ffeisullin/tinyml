# TinyML EEG — XIAO ESP32-S3

Train an EEG pattern-recognition model on the PC, quantize it to INT8 TFLite, and run it on a
Seeed XIAO ESP32-S3 with TensorFlow Lite Micro. (Qualcomm/Snapdragon work is a separate project.)

> Hobby/research project: it makes no medical or diagnostic claims (REQ-SAFE-04). Where the sleep model and its
> training data come from, in plain language: [`docs/model-provenance.md`](docs/model-provenance.md).

## Project status (2026-11-22)

| Phase | State |
|---|---|
| Toolchain smoke test on the XIAO | Done (2026-11-05) |
| A · Requirements, Python reference features, test vectors | Done (merged 2026-11-16) |
| A · Sleep-EDF baseline | Done: device features macro F1 0.680 vs 0.621 for the MNE tutorial's (REQ-ML-02 pass) |
| A · Int8 sleep model | Done in draft PR #3: running standardisation as on the device, int8 macro F1 0.707 vs 0.680 for the random forest, float/int8 agreement 98.7 % (REQ-ML-03), 6.3 KB model |
| A · Model on the XIAO | Done: outputs match Python 5/5, 224 µs per inference, 956-byte arena (REQ-ML-04) |
| B · Firmware (`eeg_node`) | The whole chain runs on the board: on a replayed held-out night its stages match Python on 100 % of epochs (REQ-FEAT-06/09/10). Acquisition firmware ready and verified with a fake 250 Hz source (task 7a); wiring and bring-up next (`docs/bringup.md`); parts due around 2026-11-26; demo 2026-11-27 |
| B · Demo display | Done (task 7d, branch `feature/demo-display`): replayed night and live views, `scripts/demo_display.py` |
| C · Oura app and hub | Oura app needed for the demo (2026-11-27), waiting on the Oura developer app registration; hub needs Docker (after the demo) |
| D · Overnight recording | Not started |

Latest work: [`docs/briefs/2026-11-22-demo-display.md`](docs/briefs/2026-11-22-demo-display.md) (demo display), [`docs/briefs/2026-11-22-deck-update.md`](docs/briefs/2026-11-22-deck-update.md) (summary since 2026-11-21, demo plan), [`docs/briefs/2026-11-22-acquisition.md`](docs/briefs/2026-11-22-acquisition.md), wiring-day checklist [`docs/bringup.md`](docs/bringup.md), [`docs/briefs/2026-11-21-end-to-end-replay.md`](docs/briefs/2026-11-21-end-to-end-replay.md), [`docs/briefs/2026-11-21-feature-parity.md`](docs/briefs/2026-11-21-feature-parity.md) and [`docs/briefs/2026-11-21-int8-sleep-model.md`](docs/briefs/2026-11-21-int8-sleep-model.md).
New to the project? Start with [`docs/getting-started.md`](docs/getting-started.md).
Full state, the laptop environment, next tasks and the handoff log are in
[`docs/STATUS.md`](docs/STATUS.md). Requirements are in
[`docs/requirements.md`](docs/requirements.md). Claude Code reads
[`CLAUDE.md`](CLAUDE.md) on start-up.

**How work is shared:** a Claude cloud session (claude.ai) writes design,
requirements and Python reference code and opens PRs; Claude Code on the laptop
runs anything that needs the laptop (board, COM ports, PhysioNet downloads,
Oura API). Both work on feature branches, log every change in
`docs/STATUS.md`, and Farid merges into `master`. A Notion page, "TinyML EEG —
Project Status & Handoff", mirrors the status file.

## Toolchain (set up 2026-11-05)

| Side | Component | Version |
|---|---|---|
| PC | Python (venv in `venv/`) | 3.12.10 |
| PC | TensorFlow / numpy / scipy / scikit-learn / pandas / matplotlib / MNE | 2.21.0 / 2.5.4 / 1.18.1 / 1.9.1 / 3.1.1 / 3.11.2 / 1.13.2 |
| Board | Arduino IDE / ESP32 core | 2.3.10 / 3.3.12 |
| Board | `Chirale_TensorFLowLite` (TFLite Micro) | 2.0.0 |
| Board | FQBN | `esp32:esp32:XIAO_ESP32S3` |

## Layout

| Path | Purpose |
|---|---|
| `docs/requirements.md` | Numbered requirements with how each is verified; the reference for code and tests |
| `eegml/` | Python reference signal processing: filters, band powers (incl. sigma), skew, kurtosis, quality metrics, 30 s epochs |
| `scripts/sleep_edf_baseline.py` | Sleep-EDF Fpz-Cz baseline: device features vs MNE-tutorial features, leave-subjects-out |
| `eegml/sleep_model.py` | Sleep-model input (per-session standardisation, clip, previous 2 epochs), int8 conversion, C-header export |
| `scripts/train_sleep_model.py` | Int8 sleep-stage model: same split as the baseline, float vs int8 report, exports `firmware/eeg_node/sleep_model.h` |
| `scripts/demo_display.py` | Demo window: the board staging a replayed night next to the experts' hypnogram, or live band power and relative alpha (task 7d) |
| `scripts/live_log.py` | Starts a live session on the XIAO (fake source or ADS1115), saves the output, summarises rate, errors and band powers |
| `scripts/replay_night.py` | Streams a Sleep-EDF night to the XIAO over USB and compares the board's features, model outputs and stages with Python |
| `scripts/calibration_ablation.py` | How the standardisation statistics (whole night, first minutes, running) change the model's results |
| `reports/` | Baseline, sleep-model and calibration-ablation reports |
| `firmware/eeg_node/` | `eeg_node.ino` (self-tests + serial replay of recorded nights), `eeg_features.h` (C++ filters and window features), `eeg_pipeline.h` (epoch summaries, running standardisation, model input), `acquisition.h` (ADS1115 driver and core-0 acquisition task), generated `eeg_config.h` (constants from `eegml/config.py`), `sleep_model.h` (int8 model, test epochs) and `feature_vectors_v1.h` (copy of the vectors) |
| `scripts/export_test_vectors.py` | Writes reference vectors for checking the firmware against Python, and `firmware/eeg_node/eeg_config.h` |
| `tests/` | `pytest` suite (filters, features, epochs, vectors, Sleep-EDF path) |
| `firmware/test_vectors/` | Generated C header of the reference vectors |
| `scripts/smoke_test.py` | Synthetic alpha/beta EEG → 1D-CNN → INT8 TFLite → `firmware/eeg_smoke/model.h` |
| `firmware/eeg_smoke/` | Sketch that runs the model on embedded test windows, prints prediction + µs |

## Commands

```powershell
# Python side
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pytest                                 # all tests
.\venv\Scripts\python.exe scripts\sleep_edf_baseline.py --subjects 20  # downloads Sleep-EDF, writes reports\
.\venv\Scripts\python.exe scripts\export_test_vectors.py             # after any change to eegml/
.\venv\Scripts\python.exe scripts\train_sleep_model.py               # cached features only; writes reports\ and firmware\eeg_node\sleep_model.h
.\venv\Scripts\python.exe scripts\calibration_ablation.py            # standardisation ablation report
.\venv\Scripts\python.exe scripts\replay_night.py --subject 20 --port COM5  # whole night through the XIAO (~7 min)
.\venv\Scripts\python.exe scripts\live_log.py --mode fake --seconds 60     # live path with a fake 250 Hz source
.\venv\Scripts\python.exe scripts\demo_display.py replay --port COM5       # demo: board stages a held-out night (--port none: no board)
.\venv\Scripts\python.exe scripts\demo_display.py live --source fake       # demo: live band power (--source adc once wired)
.\venv\Scripts\python.exe scripts\smoke_test.py

# Board side (or open firmware/eeg_smoke in Arduino IDE, board "XIAO_ESP32S3")
$cli = "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
& $cli compile --fqbn esp32:esp32:XIAO_ESP32S3 firmware\eeg_smoke
& $cli upload  --fqbn esp32:esp32:XIAO_ESP32S3 -p COMx firmware\eeg_smoke
& $cli monitor -p COMx -c baudrate=115200
```

## Notes
- `tf.lite.Interpreter` is deprecated since TF 2.20 (still works); migrate to `ai-edge-litert` if it is removed.
- `ESP_TF` (Arduino lib with Espressif ESP-NN acceleration) is an option if inference is too slow.
- The first compile of the TFLite Micro library is slow (~10+ min); later builds are cached.
