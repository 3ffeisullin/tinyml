# Requirements — EEG Sleep & Brainwave Monitor (XIAO ESP32-S3)

Version 0.1 · 2026-11-16 · Owner: Farid Feisullin

This file is the reference the code and tests in this repository are checked
against. The design behind it is in the HLD and the detailed architecture
document (Claude Docs); where the two differ, this file wins and the docs are
updated to match.

**Conventions**
- "shall" = required for the demo or the stated phase; "should" = wanted, not blocking.
- **Phase** — A: Python reference · B: firmware · C: hub and Oura · D: overnight integration.
- **Status** — Done (implemented and tested in this repo) · Open (not built yet).
- **Verify** names the test, script or measurement that shows the requirement is met.

## 1. Hardware and acquisition

| ID | Requirement | Phase | Verify | Status |
|---|---|---|---|---|
| REQ-HW-01 | The front end shall be one BioAmp EXG Pill, one ADS1115 and the XIAO ESP32-S3, all powered from the XIAO's 3.3 V rail; no boost converter or level-shifting divider. | B | Wiring check against the wiring document | Open |
| REQ-HW-02 | The ADS1115 shall read the Pill differentially, OUT on A0 against a 1.65 V reference on A1 (R1 = R2 = 10 kΩ, C1 = 100 nF), PGA ±2.048 V; fallback single-ended A0 at ±4.096 V. | B | Bring-up test 1–2 (shorted-input noise, 10 Hz test tone) | Open; firmware ready (config words `0x04A0` / `0x42A0` in `eegml/acquisition.py`, tested); bring-up tests 1–2 in `docs/bringup.md` wait for the parts |
| REQ-HW-03 | Pins: SDA D4/GPIO5, SCL D5/GPIO6 at 400 kHz, ALERT/RDY D1/GPIO2 as data-ready interrupt, I2C address 0x48. | B | Firmware boot self-test finds the ADC | Open; firmware ready (`firmware/eeg_node/acquisition.h`; boot prints whether the ADC is found); waits for the parts |
| REQ-ACQ-01 | Samples shall be converted to microvolts at the electrode (ADC counts × LSB ÷ Pill gain) before any processing; the gain constant shall be set from bench calibration. | B | Known 10 Hz test signal reads back at its applied amplitude ±10 % | Open; conversion in firmware, `PILL_GAIN` is a placeholder (1000) until the bench calibration in `docs/bringup.md` step 5 |
| REQ-ACQ-02 | Sampling shall run at 250 SPS paced by the ADC's data-ready signal, with no dropped or duplicated samples over 8 h. | B | Sample counter vs. wall clock over an overnight run | Open; data-ready-paced task written; through the same path, a fake 250 Hz source ran 335 s on the XIAO with 0 missed samples (2026-11-22). Real ADC rate (oscillator ±10 %) to be measured |
| REQ-ACQ-03 | Acquisition shall run in a core-0 task that never waits on Wi-Fi, TLS or flash. | B | Inject a 10 s broker outage; sample count unaffected | Partial (2026-11-22): acquisition task pinned to core 0 at the highest priority, independent of processing on core 1; Wi-Fi/MQTT not written yet, so the outage test waits |

## 2. Signal processing and features

All parameters live in `eegml/config.py`; the firmware shall use the same values.

| ID | Requirement | Phase | Verify | Status |
|---|---|---|---|---|
| REQ-FEAT-01 | Features shall be computed on 2 s windows (500 samples) every 1 s, symmetric Hann window, mean removed, 512-point real FFT. | A | `tests/test_features.py::test_window_counts` | Done |
| REQ-FEAT-02 | Band powers shall cover delta 0.5–4.5, theta 4.5–8.5, alpha 8.5–11.5, **sigma 11.5–15.5**, beta 15.5–30 and gamma 30–45 Hz, each band half-open [lo, hi). | A | `test_pure_tone_lands_in_its_band` | Done |
| REQ-FEAT-03 | Each band shall be reported as log10 power (µV²) and as relative power (share of 0.5–30 Hz), plus the ratios delta/beta, alpha/beta and theta/alpha. | A | `test_band_power_scale_matches_signal_power`, `test_relative_powers_of_sleep_bands_sum_to_one` | Done |
| REQ-FEAT-04 | The filter chain shall be causal biquads in this order: 60 Hz and 120 Hz notches (Q 30), 0.5 Hz 2nd-order Butterworth high-pass, 45 Hz 4th-order Butterworth low-pass; mains frequency selectable (50 Hz for European datasets). Passband gain within 1 dB from 2–30 Hz, mains rejection ≥ 30 dB. | A | `tests/test_filters.py` | Done |
| REQ-FEAT-05 | Each window shall include **skew** and **excess kurtosis** of the filtered signal (population moments, as `scipy.stats` with `bias=True`). | A | `test_moments_match_scipy`, `test_skew_kurtosis_reference_shapes`, `test_spike_raises_kurtosis` | Done |
| REQ-FEAT-06 | For sleep, window features shall be summarised per 30 s epoch as mean and standard deviation over the 29 windows that lie fully inside it. | A | `tests/test_epochs.py` | Done (Python 2026-11-16; on the XIAO 2026-11-21: 29 windows per epoch, epoch features within 7.5e-05 of Python over a replayed night, `reports/replay_sc20.md`) |
| REQ-FEAT-07 | Epochs shall be aligned to UTC 30 s boundaries on the device. | B | Epoch timestamps are multiples of 30 s | Open |
| REQ-FEAT-08 | Each window shall carry quality metrics: filtered peak-to-peak (µV), mains-to-signal power ratio on the unfiltered window, and fraction of samples within 2 % of ADC full scale. Thresholds for flags shall be set from the session's calibration recording. | A (metrics), B (flags) | `test_line_noise_metric_sees_unfiltered_hum`, `test_clip_fraction` | Metrics done |
| REQ-FEAT-09 | The firmware's filtered samples and features shall match `tests/vectors/feature_vectors_v1.json` within 1e-3 relative (log powers within 0.01) when fed the same raw samples. | A (vectors), B (device test) | `tests/test_vectors.py`; on-device parity sketch using `firmware/test_vectors/feature_vectors_v1.h` | Done (2026-11-21 on the XIAO: filtered samples within 6.5e-08 of full scale; all 20 features within tolerance, worst 0.4 %; `reports/xiao_feature_parity_2026-11-21.txt`) |
| REQ-FEAT-10 | Features shall be standardised per session with a running mean/SD before the model sees them: the first 10 epochs (5 min) are buffered and scored with their own stats, then each epoch updates the stats (Welford) and is standardised with them. The ~60 s calibration recording remains a signal-quality check. (Changed 2026-11-21 by Farid from "standardise from a ~60 s calibration": short-calibration stats drop macro F1 to 0.45, running stats keep 0.71; `reports/calibration_ablation.md`.) | A (reference), B (device) | `eegml.sleep_model.running_standardise` + tests; on the device, running stats match Python | Done (reference 2026-11-21; on the XIAO 2026-11-21: running standardisation in `firmware/eeg_node/eeg_pipeline.h`, stages identical to Python on all 1,023 epochs of a replayed night, `reports/replay_sc20.md`) |
| REQ-FEAT-11 | HMM state features (state means, SDs, time in state) on the per-second band-power series should be evaluated as extra sleep features. | A | Ablation in the Sleep-EDF baseline | Open |

## 3. Machine learning

| ID | Requirement | Phase | Verify | Status |
|---|---|---|---|---|
| REQ-ML-01 | Models shall be developed on Sleep-EDF's `EEG Fpz-Cz` channel (closest public match to the Fp1–mastoid headband), resampled to 250 Hz and run through the same feature pipeline as the device. | A | `scripts/sleep_edf_baseline.py`; `tests/test_sleep_edf.py` | Done (first run 2026-11-16, 20 subjects) |
| REQ-ML-02 | Sleep-stage models (W, N1, N2, N3, REM) shall be evaluated with leave-subjects-out cross-validation and shall at least match the MNE tutorial's feature set under the same split, reporting accuracy, macro F1, per-stage recall and the confusion matrix. Reference: MNE tutorial 68.7 % accuracy, macro F1 0.57 (two EEG channels, one train / one test subject). | A | `reports/sleep_edf_baseline.md` | Done (2026-11-16: device macro F1 0.680 vs 0.621, accuracy 0.774 vs 0.729) |
| REQ-ML-03 | Models shall be quantised to int8; the int8 model shall agree with the float model on ≥ 98 % of held-out epochs, with both results reported. | A | Conversion script report | Done (2026-11-21: 98.68 % agreement on held-out epochs, model v2 with running standardisation and per-tensor int8; `reports/sleep_model.md`) |
| REQ-ML-04 | The deployed model shall fit in 64 KB of flash and a 32 KB tensor arena, and run in under 50 ms per epoch on the ESP32-S3. | B | Serial log from the device (arena used, µs per inference) | Done (2026-11-21 on the XIAO: 6,336-byte model, arena used 956 bytes, 224 µs per inference, int8 outputs match Python 5/5; `reports/xiao_bench_2026-11-21.txt`) |
| REQ-ML-05 | An artifact detector shall gate the sleep model; flagged epochs are excluded from staging and counted. | A, B | Artifact fraction in epoch records | Open |
| REQ-ML-06 | Each model shall carry a version and the feature-schema version it expects; firmware shall refuse a mismatch. | B | Load a model with the wrong schema; device rejects it | Partial (2026-11-21): the header carries `SLEEP_MODEL_VERSION` and `SLEEP_MODEL_FEATURE_SCHEMA`; `eeg_node.ino` refuses a schema mismatch at start-up. Not yet tested with a wrong-schema model. |

## 4. Device-to-hub interface

| ID | Requirement | Phase | Verify | Status |
|---|---|---|---|---|
| REQ-IF-01 | The device shall publish 1 s feature records and 30 s epoch records over MQTT with TLS on port 8883, topics `eeg/<device>/features`, `eeg/<device>/epochs`, `eeg/<device>/status`. | B | Records arrive at the broker | Open |
| REQ-IF-02 | Every record shall carry device ID, UTC timestamp (NTP-synced), sequence number, firmware, model and schema versions. | B | Ingest schema validation | Open |
| REQ-IF-03 | When the broker is unreachable, records shall be buffered (PSRAM, spilling to flash) and replayed oldest-first; gaps shall be recorded, never interpolated. | B, C | 10 min Wi-Fi outage loses no records | Open |

## 5. Hub and Oura integration app

The Oura app is a Python service in the hub's Docker Compose stack, with a small
web page to connect the Oura account; data goes to InfluxDB and Grafana.

| ID | Requirement | Phase | Verify | Status |
|---|---|---|---|---|
| REQ-OURA-01 | The app shall use Oura API v2 with OAuth2 authorization-code sign-in (personal access tokens are retired), registered on Oura's developer portal with a localhost redirect URL. | C | Sign-in round trip on the connect page | Open |
| REQ-OURA-02 | Scopes shall be the minimum needed: `daily` (sleep periods, daily sleep and readiness) and `heartrate`. | C | Scope list in the authorize URL | Open |
| REQ-OURA-03 | Tokens shall be stored encrypted at rest, readable only by the Oura service, and refreshed before expiry without user action. | C | Restart the stack after token expiry; pull still succeeds | Open |
| REQ-OURA-04 | The app shall pull nightly and re-pull the last 3 days on each run to catch late ring syncs, storing sleep periods, the 5-minute hypnogram, heart rate and HRV. | C | Records for 3 consecutive nights present after one run | Open |
| REQ-OURA-05 | All Oura timestamps shall be converted to UTC before storage. | C | Unit test with a timezone-offset sample | Open |
| REQ-OURA-06 | A sandbox mode shall run the same code against Oura's sandbox endpoints, so the app can be built and tested without a live ring. | C | Test suite runs against sandbox data | Open |
| REQ-OURA-07 | The app shall handle HTTP 401 (refresh and retry once) and 429 (back off per `Retry-After`) without losing a night. | C | Mocked API tests | Open |
| REQ-OURA-08 | Each 30 s EEG epoch shall be labelled with the Oura stage whose 5-minute interval contains the epoch midpoint (deep→N3, light→N1/N2, REM→REM, awake→W); these are weak labels. | C | Join test on a known night | Open |
| REQ-OURA-09 | Use of Oura data for model training shall follow Oura's API agreement, which restricts AI processing; this is checked before any training on Oura-labelled data. | C | Recorded review of the agreement | Open |
| REQ-HUB-01 | The hub shall run Mosquitto, ingest, InfluxDB, Grafana and the Oura app with Docker Compose on a laptop (demo) or Raspberry Pi; only MQTT and Grafana exposed on the home network, nothing on the internet. | C | `docker compose up` on a clean machine | Open |

## 6. Safety

| ID | Requirement | Phase | Verify | Status |
|---|---|---|---|---|
| REQ-SAFE-01 | While electrodes are on a person, the wearable shall run from the LiPo only, with no connection to anything mains-powered. | All | Test procedure checklist | Open |
| REQ-SAFE-02 | Firmware shall refuse to record while USB VBUS is present. | B | Plug USB during recording; recording stops | Open |
| REQ-SAFE-03 | USB debugging with electrodes attached shall go through the USB isolator or a laptop running on battery. | B | Test procedure checklist | Open |
| REQ-SAFE-04 | The device and app shall be labelled as hobby/research tools that make no diagnostic claims. | All | README and app footer | Open |

## 7. Decisions recorded here

- **D-1 Band edges** (REQ-FEAT-02) follow the MNE sleep tutorial and Sleep-EDF practice instead of the HLD's earlier 0.5–4 / 4–8 / 8–13 / 13–30 Hz, so results compare directly with the published baseline; sigma is added for sleep spindles. The HLD should be updated to match.
- **D-2 Window count per epoch** is 29, not 30: only windows fully inside the epoch are used, so no epoch borrows signal from its neighbour.
- **D-3 Skew and kurtosis** are computed on the filtered time-domain signal without the Hann taper, so they describe the signal's amplitude distribution, not the window shape.
- **D-4 Movement features** from the Palma et al. maze study (path length, angle, speed, idle time) are out of scope; only the EEG feature-engineering ideas are reused.

## 8. Traceability

| Module / script | Requirements |
|---|---|
| `eegml/config.py` | FEAT-01, 02, 04 |
| `eegml/filters.py` | FEAT-04 |
| `eegml/features.py` | FEAT-01, 02, 03, 05, 08 |
| `eegml/epochs.py` | FEAT-06 |
| `eegml/sleep_edf.py`, `scripts/sleep_edf_baseline.py`, `tests/test_sleep_edf_real.py` | ML-01, ML-02 |
| `scripts/export_test_vectors.py`, `tests/vectors/`, `firmware/test_vectors/` | FEAT-09 |
| `scripts/smoke_test.py`, `firmware/eeg_smoke/` | Toolchain check (pre-requirements) |
| `.vscode/`, `docs/getting-started.md` | Team tooling (no requirement) |
