# After-demo model comparison (REQ-ML-07)

Plan written 2026-11-26; to run after the demo (Friday 2026-12-04). Results will go in
`reports/model_comparison.md` as one table.

Why: only two model kinds have been tried so far, a random forest and one small dense network on our
30 epoch features (int8 macro F1 0.707). Published single-channel Fpz-Cz models report macro F1 of about
0.77–0.82 on Sleep-EDF, but most of them see the whole night (future epochs too) and use 20-fold tests
rather than our 5-fold, so the numbers aren't comparable as they stand. This comparison puts every
candidate under one protocol.

## a) Protocol

- **Data:** all Sleep-EDF Sleep Cassette subjects with Fpz-Cz (78), 5-fold split by subject, seeded,
  with the same folds for every candidate. Also report the existing 20-subject numbers for continuity.
- **Causal only:** a model may use the current and past epochs, never future ones, with running
  standardisation as deployed (REQ-FEAT-10).
- **Metrics** (REQ-ML-07), for each candidate:
  - macro F1;
  - per-stage recall;
  - per-night deep-sleep error in minutes (MAE, bias, r), using the method of
    `scripts/stage_minutes_report.py`;
  - on-device cost: int8 size, arena, µs per epoch, or "does not fit".

## b) Candidates

In this order:

| ID | Candidate | Notes |
|---|---|---|
| C0 | Current int8 dense net (baseline) | 20 and 78 subjects |
| C1 | C0 plus stage-transition smoothing | A causal HMM forward pass over the net's outputs; transition matrix learned on the training folds |
| C2 | Longer context | A small GRU or 1D temporal convolution over the last 10–20 epochs of the 30 features |
| C3 | LightGBM on the same input as C0 | Tabular baseline; record its size |
| C4 | One compact raw-EEG network | LWSleepNet or NanoSleep class, about 180–350 K parameters, on the 30 s raw epoch, made causal. Report whether its int8 version fits the XIAO's PSRAM, and its time per epoch |

## c) Decision rule

Choose the candidate with the best macro F1 that does not make the per-night deep-sleep MAE worse and
fits the device. A gain under 0.01 macro F1 doesn't justify a firmware change.

## d) Note on deep sleep

The per-night deep-sleep error comes mostly from per-night scaling
([`reports/deep_sleep_scale_ablation.md`](../reports/deep_sleep_scale_ablation.md)), so REQ-FEAT-12
(slow-wave and spindle features) runs alongside whichever model wins.

## e) Literature reference points

Cited for context only; we don't copy their code. All are **non-causal, different folds: not directly
comparable**.

| Model | Reported result | Size |
|---|---|---|
| DeepSleepNet | Sleep-EDF: accuracy 82.0 %, MF1 76.9 | |
| LWSleepNet | Sleep-EDF-20: accuracy 86.6 %, MF1 79.2 | 180 K parameters |
| NanoSleep | accuracy 86.5 %, MF1 82.1 | 0.35 M parameters |
| TinySleepNet | | 1.3 M parameters |
