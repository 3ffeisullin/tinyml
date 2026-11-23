# Brief: update the progress slide deck (2026-11-22)

For the Claude cloud session, to update the progress deck that was built from the 2026-11-21 prompt. Repo
`3ffeisullin/tinyml`, branch `feature/int8-sleep-model`, draft PR #3 (not merged). Every number below
comes from the file named next to it; quote them exactly.

## 1. What changed since the 2026-11-21 deck prompt

The deck prompt was written after task 6, while task 6b was in progress. Since then:

| Change | Numbers | Source |
|---|---|---|
| **Task 6b done: the whole chain runs on the XIAO.** Raw samples → filters → 1 s window features → 30 s epoch summaries → running standardisation → 3-epoch stack → int8 model → stage, all on the board. A held-out Sleep-EDF night (subject 20, not in training) was streamed to the board over USB and checked against Python epoch by epoch. | 1,023 epochs (8.53 h; 1,022 staged by the hypnogram). **Stages identical to Python on 100 % (0 disagreements).** Epoch features within 7.5e-05 (99th percentile 2.5e-07). Int8 model outputs byte-identical on 97.85 % of epochs; the rest differ by at most 8 LSB and never change the stage. Board time 281 ms per 30 s epoch (median; max 287 ms), about 100× faster than real time. | `reports/replay_sc20.md`, `.json`, `.csv`; `docs/briefs/2026-11-21-end-to-end-replay.md` |
| **Accuracy on that one held-out night** (board = Python) | Accuracy 0.670, macro F1 0.466. Recall W 0.75, N1 0.46, N2 0.76, N3 1.00 (only 4 N3 epochs that night), REM 0.32. Main errors: REM → W (80 of 177 REM epochs), N2 → N3 (81 epochs). Below the cross-validated range (fold accuracy 0.71–0.81); one night is a small sample. | `reports/replay_sc20.md` |
| **Task 7a done: acquisition firmware ready before the parts.** ADS1115 driver; a core-0 task woken by the ADC's data-ready pin feeds a queue to processing on core 1. Tested with a fake ADC (a 250 Hz timer replaying a reference signal through the same path). | 335 s live run: 83,751 samples at 250.00 Hz, **0 missed samples, 0 I2C errors, 0 queue overflows**. First 11 live windows match Python (worst 0.4 % of tolerance). Sketch: 401 KB flash (11 %), 95 KB RAM (28 %). | `reports/xiao_live_fake_2026-11-22.txt`; `docs/briefs/2026-11-22-acquisition.md` |
| **Wiring-day checklist written** | Safety, wiring table, ADC probe, resting voltages, noise floor and sample rate, 10 Hz gain calibration, eyes open/closed. | `docs/bringup.md` |
| **Decisions from Farid (2026-11-22)** | (1) Build the laptop demo display. (2) Gain calibration with a signal generator: 100 mV p-p, 10 Hz sine through a 100 kΩ / 100 Ω divider ≈ 100 µV p-p at the Pill (a phone tone app is unreliable at 10 Hz). (3) **The demo shows Oura data**, which moves the Oura app (task 5) onto the demo's critical path. | `docs/STATUS.md` §4, §6 |
| **Model provenance documented** | Trained from scratch by our scripts on Sleep-EDF (PhysioNet, ODC-By 1.0); no pre-trained model. | `docs/model-provenance.md` |
| Tests | 47 pass (44 at the time of the deck prompt). | `python -m pytest` |

## 2. Current state

| Item | State |
|---|---|
| Task 6b (end to end on the board, replayed night) | **Done** 2026-11-21 (see above). REQ-FEAT-06 and REQ-FEAT-10 done on the device. |
| Task 7a (acquisition firmware) | **Done** 2026-11-22 with a fake ADC. Not yet proved: the ADS1115's I2C reads, its data-ready interrupt and its real sample rate. |
| Task 7 (wiring and bring-up) | **Waiting for parts.** Checklist ready (`docs/bringup.md`). |
| Task 7d (laptop demo display) | **Next**, approved by Farid: live band powers / relative alpha from the board, and a hypnogram that builds up epoch by epoch as the board stages a replayed night. |
| Task 5 (Oura app) | **Needed for the demo** now. Plain Python on the laptop (no Docker): OAuth sign-in, pull the last night's sleep stages. Blocked until the Oura developer app is registered (open question for Farid). |
| Parts | In hand: resistors, capacitors, electrodes. Ordered: BioAmp EXG Pill, ADS1115 and the rest, **due around 2026-11-26**, one day before the demo. |
| Demo | **Thursday 2026-11-27.** |
| PR #3 | Draft, not merged; holds tasks 4–7a. |

### Demo plan

**Plan A (parts arrive and bring-up works):**
1. Live signal from the headband on a person: band powers on the laptop display; relative alpha rises with eyes
   closed. **Battery or USB isolator only** (REQ-SAFE).
2. The board staging a replayed Sleep-EDF night, with the hypnogram building up live next to the true one.
3. Oura: Farid's own recent night (sleep stages, HR/HRV) from the Oura API, shown as the comparison the system is
   built for. It's context, not validation: the Oura night and the replayed EEG night are different people and nights.
4. The on-device checks: feature parity, model parity, timing.

**Plan B (parts late or bring-up fails):** items 2–4 only. Nothing in Plan B depends on the parts.
If Oura API access isn't ready either, item 3 falls back to a screenshot from the Oura app.

### Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Parts arrive around 11-26, one day before the demo | Little time for bring-up | Plan B; checklist and firmware ready; fake-ADC path already verified |
| ADS1115 internal oscillator is ±10 % | Real rate 225–275 Hz; band edges shift with it | Measure the rate at bring-up (`STAT`); pace from the XIAO or correct `EEG_FS` if off by > 1 % |
| BioAmp EXG Pill at 3.3 V (vendor docs list 5 V) | Output may not centre at 1.65 V | Measure at bring-up; fallback single-ended ±4.096 V is one command (`LIVE ADC SE`) |
| Pill gain is a placeholder (1000) | Absolute µV readouts wrong until calibrated; **staging unaffected** | 10 Hz calibration (`docs/bringup.md` step 5) |
| Oura API access needs a registered developer app | No live Oura data in the demo | Farid registers the app now; fallback: screenshot |
| Accuracy varies by night (held-out night 0.670 vs CV 0.768) | Demo staging may look worse than the headline number | Quote the CV figure as the model's accuracy; present the replay as "the board reproduces the reference exactly" |
| Single channel confuses REM and wake | REM recall 0.32 on the held-out night | Known limit of one forehead channel; model improvements after the demo |
| Mains-powered signal generator during calibration | Electrical safety | Bench-only test; no electrodes on a person while it's connected |
| Domain shift: training data is Fpz-Cz from a 1987–91 study; our headband is Fp1–mastoid | Unknown accuracy on our own recordings | Phase D: real nights with the headband and the Oura ring |

### Open decisions

1. Oura developer app registration: who, and when (blocks task 5 and Plan A item 3).
2. Which Oura data to show: sleep stages only, or also HR/HRV and the sleep score.
3. When to review and merge PR #3 (before or after the demo).
4. Docker Desktop install (hub, task 5b): not needed for the demo.

## 3. Numbers from 2026-11-21 that are now out of date

| Where it appeared | Old figure | Corrected figure | Why | Source |
|---|---|---|---|---|
| Deck prompt: "Task 6b (in progress)" | in progress | **done**, 100 % stage agreement on a held-out night | finished 2026-11-21 | `reports/replay_sc20.md` |
| Deck prompt: "44 automated tests pass" | 44 | **47** | tests for tasks 6b and 7a | `python -m pytest` |
| Deck prompt: Oura app "only if the demo needs Oura data" | optional | **needed** for the demo | Farid, 2026-11-22 | `docs/STATUS.md` §4 |
| Deck prompt: "Remaining: 6b, 7a, 7" | 6b and 7a open | **6b and 7a done**; remaining: 7d display, 5 Oura app, 7 wiring | | `docs/STATUS.md` §5 |
| Brief `2026-11-21-int8-sleep-model.md` (main part): int8 model, whole-night standardisation | acc 0.796, macro F1 0.739, agreement 99.20 %, 7,536 B, trained 11 epochs | **acc 0.768, macro F1 0.707, agreement 98.68 %, 6,336 B, trained 19 epochs** (model v2: running standardisation, per-tensor int8) | v1 used whole-night statistics the device can't have; per-channel int8 didn't run correctly on the XIAO's TFLite Micro | `reports/sleep_model.md`, `.json` |
| Same brief, addendum 1: int8 accuracy and agreement for v2 | 0.769, 98.72 % | **0.768, 98.68 %** | per-tensor quantisation (task 4b fix) | `reports/sleep_model.md` |
| Same brief: arena estimate | 3,156 B (7,168 allocated) | **956 B measured on the XIAO** (7,168 allocated) | the estimate was conservative | `reports/xiao_bench_2026-11-21.txt` |
| Same brief: model size | 7,536 B | **6,336 B** | per-tensor weights | `reports/sleep_model.md` |

Unchanged and still correct: baseline random forest 0.774 / 0.680; calibration ablation (whole night 0.740, first 60 s 0.450, running 0.710 macro F1); on-board inference 224 µs; feature parity 6.5e-08 / worst 0.4 %; filter 17 µs per sample, features 5.2 ms per window.

## 4. Suggested slide changes

- "What's done": add the whole-chain-on-board result (100 % stage agreement, 0.28 s per epoch) and the acquisition firmware (0 missed samples in 335 s).
- "Model results": use the v2 numbers above; add the held-out-night result with its caveat.
- "Demo plan": Plan A / Plan B as above, with Oura in both.
- "Remaining work": 7d display, 5 Oura app, 7 wiring and bring-up (parts around 11-26), then Phase D real nights.
- "Risks" and "Asks": as above; the main asks are the Oura developer app registration and the PR #3 review.
- New slide (optional): "Where the model comes from", from `docs/model-provenance.md`.
