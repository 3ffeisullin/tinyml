# Brief: task 6b, the whole chain on the XIAO on a replayed night (2026-11-21, Claude Code)

For the Claude cloud session and Farid's review. Branch `feature/int8-sleep-model`, draft PR #3. Follows
`docs/briefs/2026-11-21-feature-parity.md` (task 6) and `docs/briefs/2026-11-21-int8-sleep-model.md` (model).

## What ran

The laptop plays the headband: `scripts/replay_night.py` streams a Sleep-EDF night (Fpz-Cz, resampled to 250 Hz,
float32) to the XIAO one 30 s epoch at a time. The board runs **everything** on its own: 50 Hz filter chain →
window features every second → 30 s epoch summaries (29 windows, mean/SD) → running standardisation
(Welford, 10-epoch warm-up) → [t, t-1, t-2] stack → int8 quantisation → int8 model → stage. Python runs the same
chain on the same samples. **Subject 20 is not one of the model's 20 training subjects (0–19): a held-out night.**
Full report: `reports/replay_sc20.md` (+ `.json`, per-epoch `.csv`).

## Board vs Python: the device pipeline is correct

| Check (1,023 epochs, 8.5 h) | Result |
|---|---|
| Windows per epoch | 29 every epoch |
| Epoch features, max relative error | 7.5e-05 (99th percentile 2.5e-07) |
| Int8 model outputs identical | 97.85 % of epochs; the other 22 differ by at most 8 LSB, and none changes the stage |
| **Stage agreement** | **100 % (1,023 / 1,023)** |
| Board time per 30 s epoch | 281 ms median, 287 ms max (about 100× faster than real time) |

The small int8 differences come from float32 features on the board vs float64 in Python: now and then a
standardised input lands on the other side of a quantisation step. One step of input moves the output by a
few LSB, never enough to flip a stage on this night.

## Board vs the hypnogram (one held-out night)

| | Accuracy | Macro F1 | W | N1 | N2 | N3 | REM |
|---|---|---|---|---|---|---|---|
| Board (= Python) | 0.670 | 0.466 | 0.75 | 0.46 | 0.76 | 1.00 | 0.32 |
| Cross-validated, 20 subjects (`reports/sleep_model.md`) | 0.768 | 0.707 | 0.78 | 0.43 | 0.78 | 0.80 | 0.81 |

Stage columns are recall. Class counts this night: W 263, N1 39, N2 539, N3 4, REM 177.

**Reading:** this night is below the cross-validated range (fold accuracy 0.71–0.81). Two errors dominate:
- **REM → W (80 of 177 REM epochs).** Single-channel EEG has no eye-movement or muscle channel, and REM and
  relaxed wake look alike on the forehead.
- **N2 → N3 (81 epochs)** in a night with almost no N3 (4 epochs). Macro F1 is then dragged down by N3's
  precision (4 true vs 90 predicted).

One night is a small sample. The figure to quote for the model is still the cross-validated 0.707 macro F1. For
the demo, the honest claim is: "the board reproduces the reference pipeline exactly; staging quality is that of
the model, not limited by the device."

## Built

| File | What it is |
|---|---|
| `firmware/eeg_node/eeg_pipeline.h` | `eeg::EpochFeatures` (stream raw samples → 30 epoch features) and `eeg::ModelInput` (Welford running standardisation, warm-up flush, 3-epoch stack), plus `quantise_input` (float32 maths with round-half-even, like numpy 2). |
| `firmware/eeg_node/eeg_node.ino` | Stage 3: self-tests at boot (feature parity, model bench), then a serial replay protocol: `BEGIN <Hz>`, `EPOCH` + 7,500 float32 in 4 KB chunks each acknowledged with `C`, `END`, `TEST`. Replies `FEAT`, `OUT`, `ACK`. 395 KB flash (11 %), 94 KB RAM (28 %). |
| `scripts/replay_night.py` | Laptop side: downloads the night once, builds the Python reference, drives the board, writes the report. |
| `eegml/sleep_edf.py` | `device_segment` (the signal the device would record) and `device_epoch_features` factored out of `subject_features`; they reproduce the cached training features bit for bit. |
| Tests | 2 new (device segment with a movement-time gap; board line parsing); 46 pass. `pyserial` added to `requirements.txt` and the lock file. |

## Found on the way

1. **USB serial drops data without flow control.** Sending a 30 KB epoch in one write lost about 12 KB on the
   board (its 8 KB receive buffer overflowed). The protocol now sends 4 KB chunks and waits for an acknowledgement after each.
2. **Unscored epochs are still signal.** Hypnograms contain "Movement time" / "?" epochs. The device can't
   know about them, so the replay sends the continuous recording, both sides process every epoch, and only
   staged epochs are scored. (Training skipped those epochs, so its 3-epoch stack occasionally spans a gap;
   a minor training/device mismatch to remove when the model is next retrained.)
3. **numpy 2 quantises in float32.** `Int8Runner.quantise` divides a float32 array by a Python float, which stays
   float32 under numpy 2's promotion rules. The board does the same so rounding matches.

## Next

| # | Task | Notes |
|---|---|---|
| 7a | ADS1115 driver and 250 Hz acquisition loop feeding `EpochFeatures`, written and compiled before the parts arrive; a fake-ADC mode (e.g. replayed samples through the same path). | Leaves only wiring for the day the parts arrive. |
| 7 | Wire the Pill and ADS1115 (due around 2026-11-26); live band powers; 60 Hz chain. Electrodes on a person only with the XIAO on battery, through the USB isolator, or with the laptop on battery (REQ-SAFE). | |
| Demo | Show the replayed night staging live on the board (hypnogram building up epoch by epoch), the parity numbers, and live signal if the parts make it. A small laptop script could plot the board's stages against the hypnogram as they arrive. | Fallback needs no parts. |
| Model | Retrain with unscored epochs kept in the stack, more Sleep-EDF subjects (about 78 available), and maybe temporal smoothing (REQ-FEAT-11) to cut the REM ↔ W and N2 ↔ N3 confusions. | After the demo. |
