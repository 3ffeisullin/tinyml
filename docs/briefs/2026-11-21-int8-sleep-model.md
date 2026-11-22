# Brief: task 4, int8 sleep model (2026-11-21, Claude Code on the laptop)

For the Claude cloud session and for Farid's review of draft PR #3. Self-contained; the details
are in `reports/sleep_model.md`, `reports/calibration_ablation.md` and `docs/STATUS.md`.

## Where things are

- Repo `3ffeisullin/tinyml`, branch `feature/int8-sleep-model`, **draft PR #3** (not merged).
  Commits: `90fe830` (cloud: specs), `fb8bc14` (task 4), then this brief, the calibration ablation and the doc updates.
- `master` is unchanged at `309a1bf`. Tests on the branch: **39 pass** (32 before, plus 7 in `tests/test_sleep_model.py`).
- Data: 20 Sleep-EDF SC subjects (sc00–sc19, 20,626 scored epochs) from the cache in `data/cache/sleep_edf/`
  (git-ignored, laptop only). Nothing was re-downloaded.

## What was built

| File | What it does |
|---|---|
| `eegml/sleep_model.py` | The model-input steps the firmware has to copy: `standardise`, `stack_neighbours`, `model_input`. Also `build_model`, `to_int8` (full-integer PTQ), `Int8Runner`, and the header writer/reader. |
| `eegml/config.py` | New parameters `SLEEP_NEIGHBOURS = 2`, `SLEEP_INPUT_CLIP = 6.0`, `SLEEP_SD_FLOOR = 1e-6` (all processing parameters live here). |
| `scripts/train_sleep_model.py` | 5-fold `GroupKFold` over subjects (the baseline's exact split). Per fold: float net with early stopping on 3 training subjects, int8 conversion using a representative set from that fold's training subjects only, baseline random forest, and a random forest on the net's input. Then one final model on all 20 subjects, exported to the header. Seeded and reproducible (two runs gave identical numbers). |
| `scripts/calibration_ablation.py` | Tests how the standardisation statistics change the results (see below). |
| `reports/sleep_model.md/.json`, `reports/calibration_ablation.md/.json` | Results. |
| `firmware/eeg_node/sleep_model.h` | The int8 model (`g_sleep_model`, 7,536 bytes, 16-byte aligned) plus `#define`s for version, feature schema (1), input layout (30 features × [t, t-1, t-2] = 90), clip, input/output scale and zero point, arena size (7,168), stage names and feature order. It also has one int8 test input per stage (`g_sleep_in_<stage>`) with the expected int8 output (`g_sleep_out_<stage>`) for the on-device parity check in task 4b. |
| `tests/test_sleep_model.py` | Neighbour windowing (order, padding at the start, causal, no mixing across sessions), standardisation incl. constant features, clipping, config consistency, header round trip, and the generated header: loads, fits the limits, and reproduces its embedded outputs. |

**Model input, as the firmware must build it:** z-score each of the 30 epoch features with the
session's mean/SD → clip to ±6 → concatenate current, previous and previous-but-one epoch (at the
start of a session the missing ones repeat the first epoch) → quantise with
`round(x / 0.0417195633) - 17`, clamped to int8. Output: 5 int8 scores (scale 1/256, zero point -128) for W, N1, N2, N3, REM; take the argmax.
**Model:** Dense 32 relu → Dropout 0.2 → Dense 16 relu → Dropout 0.2 → Dense 5 softmax, 3,525 parameters,
inverse-square-root class weights, Adam 2e-3, batch 128. The final model trained for 11 epochs (median of the folds' early-stopping points).

## Results (held-out subjects, whole-night standardisation)

| Model | Accuracy | Macro F1 | W | N1 | N2 | N3 | REM |
|---|---|---|---|---|---|---|---|
| Net, float | 0.796 | 0.739 | 0.83 | 0.50 | 0.80 | 0.84 | 0.81 |
| Net, int8 | 0.796 | 0.739 | 0.83 | 0.50 | 0.80 | 0.84 | 0.81 |
| Random forest, baseline | 0.774 | 0.680 | 0.84 | 0.20 | 0.85 | 0.83 | 0.68 |
| Random forest, net's input | 0.813 | 0.737 | 0.87 | 0.31 | 0.87 | 0.75 | 0.84 |

Stage columns are recall. Float/int8 agreement: 99.20 % held out (folds 98.99–99.55 %) → **REQ-ML-03 Done**.
Size 7,536 bytes (64 KB limit); arena estimate 3,156 bytes, 7,168 allocated (32 KB limit) →
REQ-ML-04 is met on paper but stays Open until the board measures it (task 4b).
Per-fold float accuracy ranges from 0.766 to 0.829, so the spread between subjects is about ±3 points.

## Insights

1. **The gain comes mostly from the input, not the net.** A random forest given the same standardised,
   stacked input matches the net's macro F1 (0.737 vs 0.739). Per-subject normalisation and two epochs of
   context are what count. The net is still the right choice for the device: it is 7.5 KB, runs on TFLM,
   and gets N1 recall of 0.50 where the forest gets 0.31.
2. **REQ-FEAT-10 as written would undo the gain (biggest finding).** The report uses whole-night mean/SD,
   which the device can never know. With stats from the first 60 s / 5 min / 10 min (wake, before sleep), the same model
   drops to macro F1 0.45–0.46, far below the random forest's 0.68 (`reports/calibration_ablation.md`).
   Wake features don't describe the sleep distribution.
3. **The fix is causal running standardisation.** Mean/SD are updated each epoch from the start of the
   session (Welford's method, 30 means + 30 variances, 10-epoch warm-up), and the model is trained the same way.
   Result: accuracy 0.770 / macro F1 0.710 (N1 0.47, REM 0.83), still above the random forest, and it
   works on the device. If a model trained on whole-night stats is fed running stats, it gets only 0.654, so it must be retrained.
4. **Quantisation is not the problem.** Int8 matches float to three decimals. The input quantisation
   range is asymmetric (about −4.6 to +6.0 in standardised units), so very negative values saturate. That costs nothing
   measurable today; a symmetric clip is an option if agreement slips after retraining.
5. **N1 remains the weak class:** int8 N1 recall 0.50 but precision 0.35 (F1 ≈ 0.41), mostly because
   483 N2 epochs and 344 REM epochs are called N1. Published single-channel Fpz-Cz models (e.g. DeepSleepNet)
   report N1 F1 around 0.4–0.5 too, so this is close to what one channel allows.
6. **Not yet measured:** domain shift from Sleep-EDF (Fpz-Cz, 100 Hz upsampled, 50 Hz mains) to the
   headband (Fp1–mastoid, 250 Hz, 60 Hz mains), and only 20 of the ~78 Sleep-EDF SC subjects were used.

## Decisions needed from Farid

1. **REQ-FEAT-10:** change from "standardise from a ~60 s calibration" to "standardise with a running
   per-session mean/SD (10-epoch warm-up); the 60 s calibration remains a signal-quality check".
   Recommended, given the ablation.
2. **Order of next tasks** (recommendation below).
3. Still open from before: parts order and arrival date (the 2026-11-20 demo date has passed), Oura developer app
   registration, Docker Desktop install.

## Recommended next steps

| # | Task | Where | Notes |
|---|---|---|---|
| 4a | Retrain with running standardisation (flag in `train_sleep_model.py`, running as the default), re-export `sleep_model.h`, re-check int8 agreement, add a test that the Python running stats match a Welford reference | Laptop, ~1 h | Needs decision 1. Makes the header match what the device can do. |
| 4b | Run the model on the XIAO: embedded test epochs must reproduce `g_sleep_out_*`; print arena used and µs per inference | Laptop + XIAO, no electrodes | Closes REQ-ML-04. Can use the current header (same architecture), so it doesn't strictly wait for 4a. |
| 5 | Oura app skeleton (`hub/oura_app/`) | Laptop | Needs the Oura developer app registered. |
| later | More Sleep-EDF subjects (~78 SC subjects); temporal smoothing / HMM (REQ-FEAT-11); artifact gate (REQ-ML-05); schema check on the device (REQ-ML-06) | Laptop | More subjects is the cheapest accuracy gain to try. |

## Addendum, same day: task 4a done, task 4b sketch ready

Farid approved the REQ-FEAT-10 change and the order 4a → 4b. Parts are ordered and several have
arrived; the demo moved to **2026-11-27**.

- **Running standardisation is now the default** (`config.SLEEP_STANDARDISE = "running"`,
  `SLEEP_WARMUP_EPOCHS = 10`). Device behaviour, mirrored by `eegml.sleep_model.RunningStats`: buffer the
  first 10 epochs (5 min) and score them with their own Welford mean/population SD once the warm-up completes;
  after that, update the stats with each epoch and then standardise it. A float32 Welford stays within 1e-3
  of float64 over a 1,000-epoch night, which is far below one int8 input step (0.042).
- **Model v2** (`SLEEP_MODEL_VERSION 2`, same architecture, 7,536 bytes), held out:

| Model | Accuracy | Macro F1 | W | N1 | N2 | N3 | REM |
|---|---|---|---|---|---|---|---|
| Net v2, float | 0.769 | 0.708 | 0.77 | 0.44 | 0.78 | 0.81 | 0.82 |
| Net v2, int8 | 0.769 | 0.707 | 0.78 | 0.43 | 0.78 | 0.80 | 0.81 |
| Random forest, baseline | 0.774 | 0.680 | 0.84 | 0.20 | 0.85 | 0.83 | 0.68 |
| Random forest, v2 input | 0.785 | 0.697 | 0.82 | 0.22 | 0.85 | 0.71 | 0.83 |

  Float/int8 agreement 98.72 % (folds 98.40–98.90 %): passes REQ-ML-03, with less margin than v1's 99.20 %.
  The net beats the forest on macro F1 (0.707 vs 0.680) and N1 recall (0.43 vs 0.20) at about the same accuracy.
  The whole-night v1 numbers (0.739) remain in `reports/calibration_ablation.md` as the offline ceiling.
- **Task 4b:** `firmware/eeg_node/eeg_node.ino` checks the model's feature schema (REQ-ML-06), runs the 5
  embedded test epochs, checks the int8 outputs against Python byte for byte, times 200 inferences each and prints
  the arena used. Compiles for `esp32:esp32:XIAO_ESP32S3`: 345,453 bytes flash (10 %), 30,816 bytes RAM (9 %).
  Not yet run: the board wasn't connected.
- **Next after 4b:** for the 2026-11-27 demo, the shortest credible path is the model bench (4b) plus, as parts
  allow, the on-device feature parity test (task 6), then live acquisition (task 7). The Oura app (task 5) is not
  on the demo's critical path unless the demo needs Oura comparison data.

## Addendum 2, same evening: task 4b done on the XIAO

Bench log, first boot cycle (`reports/xiao_bench_2026-11-21.txt`):

```
Model v2, feature schema 1, input 90, arena 7168 bytes
in scale 0.0417459 zp -17, out scale 0.00390625 zp -128
Model 6336 bytes, arena used 956 / 7168 bytes
true W   -> predicted W    output matches Python  224 us/inference
true N1  -> predicted N1   output matches Python  221 us/inference
true N2  -> predicted N2   output matches Python  223 us/inference
true N3  -> predicted N2   output matches Python  221 us/inference
true REM -> predicted REM  output matches Python  223 us/inference
SUMMARY parity 5/5, worst 224 us/inference, arena used 956 bytes
```

- **REQ-ML-04 Done:** 6,336 B model (limit 64 KB), 956 B arena (limit 32 KB; the 3.2 KB estimate was conservative),
  224 µs per inference (limit 50 ms, about 220× headroom). The "N3 → N2" line is the model's own call on that test
  epoch, identical in Python. Parity compares int8 outputs byte for byte.
- **Pitfall 1, per-channel quantisation:** TF 2.21 quantises dense weights per channel by default, and the
  Arduino TFLM build (Chirale_TensorFlowLite 2.0.0) handles only per-tensor FULLY_CONNECTED weights. Tested on the
  board: a per-channel model gave 0/5 parity, with scores off by 10–50 and some predictions changed. `to_int8` now sets
  `_experimental_disable_per_channel_quantization_for_dense_layers`, and a test fails any header with per-channel
  tensors. Cost: agreement 98.72 → 98.68 %, int8 accuracy 0.769 → 0.768, same macro F1 0.707; the model shrank
  from 7,536 to 6,336 bytes.
- **Pitfall 2, input buffer reuse:** TFLM's memory planner reuses the input tensor for later activations, so
  after `Invoke()` the input holds garbage. Copy the input before every inference (the timing loop does), and
  never assume it survives. The node firmware must follow this too.
- **Demo path (2026-11-27), recommended:** task 6 (feature parity on the board with `firmware/test_vectors/`) →
  task 6b (end to end on the board: raw samples → features → running standardisation → 3-epoch buffer → model,
  checked against Python on a Sleep-EDF segment) → task 7 (live ADS1115 acquisition with the arrived parts,
  battery-powered or through the USB isolator if electrodes are on a person, REQ-SAFE). A credible demo could show
  live band powers from the headband plus the model staging a replayed Sleep-EDF night on the device.
