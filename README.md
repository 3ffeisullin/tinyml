# TinyML EEG — XIAO ESP32-S3

Train an EEG pattern-recognition model on the PC, quantize it to INT8 TFLite, and run it on a
Seeed XIAO ESP32-S3 with TensorFlow Lite Micro. (Qualcomm/Snapdragon work is a separate project.)

## Project status (2026-11-21, evening)

| Phase | State |
|---|---|
| Toolchain smoke test on the XIAO | Done (2026-11-05) |
| A · Requirements, Python reference features, test vectors | Done (merged 2026-11-16) |
| A · Sleep-EDF baseline | Done: device features macro F1 0.680 vs 0.621 for the MNE tutorial's (REQ-ML-02 pass) |
| A · Int8 sleep model | Done in draft PR #3: running standardisation as on the device, int8 macro F1 0.707 vs 0.680 for the random forest, float/int8 agreement 98.7 % (REQ-ML-03), 6.3 KB model |
| A · Model on the XIAO | Done: outputs match Python 5/5, 224 µs per inference, 956-byte arena (REQ-ML-04) |
| B · Firmware (`eeg_node`) | Model bench runs on the board; next: feature parity (task 6), end to end (6b), acquisition (7). Parts ordered, several received; demo 2026-11-27 |
| C · Oura app and hub | Not started; Oura app after the int8 model, hub needs Docker |
| D · Overnight recording | Not started |

Latest work: [`docs/briefs/2026-11-21-int8-sleep-model.md`](docs/briefs/2026-11-21-int8-sleep-model.md).
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
| `scripts/calibration_ablation.py` | How the standardisation statistics (whole night, first minutes, running) change the model's results |
| `reports/` | Baseline, sleep-model and calibration-ablation reports |
| `firmware/eeg_node/` | `eeg_node.ino` (stage 1: sleep-model bench: parity, µs, arena) and generated `sleep_model.h` (int8 model, quantisation constants, test epochs) |
| `scripts/export_test_vectors.py` | Writes reference vectors for checking the firmware against Python |
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
