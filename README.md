# TinyML EEG — XIAO ESP32-S3

Train an EEG pattern-recognition model on the PC, quantize it to INT8 TFLite, and run it on a
Seeed XIAO ESP32-S3 with TensorFlow Lite Micro. (Qualcomm/Snapdragon work is a separate project.)

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
