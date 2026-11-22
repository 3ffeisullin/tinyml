# Brief: task 7d, laptop demo display (2026-11-22, Claude Code)

For the Claude cloud session and Farid. Branch `feature/demo-display` (from `feature/int8-sleep-model`; its PR is
based on that branch and gets retargeted to `master` once PR #3 merges).

## Result

`scripts/demo_display.py` shows what the XIAO is doing, live, in one window. It has two views:

| View | What it shows | Verified (2026-11-22) |
|---|---|---|
| `replay --port COM5` | A Sleep-EDF night streamed to the board. The board's hypnogram builds up epoch by epoch under the sleep experts' hypnogram, with relative band power across the night and running scores: board = PC reference, agreement with the experts, board time per epoch. | Whole held-out night (subject 20, 1,023 epochs, ~7.5 min): **board = PC 100.0 %, agreement with experts 67.0 %, 286 ms per epoch (median)**, matching `reports/replay_sc20.md`. Image: `reports/demo_replay_sc20_2026-11-22.png`. |
| `replay --port none` | The same from the PC reference, without a board: for rehearsal, and the fallback if the board fails on the day. | Whole night, 67.0 % agreement. |
| `live --source fake\|adc\|adc-se` | The board's live path: log band power and relative alpha over the last 2 minutes, stages after the 5-minute warm-up, sample rate, missed samples / I2C errors / overflows, peak-to-peak, mains ratio, clipping. | Fake source: 249.98 Hz, 0 / 0 / 0, fake-source parity PASS. Image: `reports/demo_live_fake_2026-11-22.png`. ADC modes wait for the parts. |

`--save PATH` writes a PNG at the end and `--headless` runs without a window; both are used for slides and tests.

## Design notes

- The board conversation is shared with `replay_night.py`, not copied. That script's
  `prepare_night` / `open_board` / `send_epoch` / `end_session` were factored out; a 15-epoch re-run of
  `replay_night.py` still gives 100 % stage agreement.
- Every quantity has one definition. The live view plots the board's own `rel_alpha` and log band powers. It does
  not recompute band shares, because the board's relative power is measured against total power, including the
  gaps between bands. The replay view's stack is labelled "share of band power" (the six relative powers rescaled
  to sum to 1).
- Colours follow the dataviz reference palette: bands in fixed categorical order (the same colour for alpha in
  both views), the experts' hypnogram in grey, the board in blue, text in neutral ink, one y-axis per chart.
- Errors in the background thread (board not found, a timeout) appear in red in the window rather than being
  lost.
- Tests: `tests/test_demo_display.py` checks the parser against every line format the firmware prints. 51 tests pass.

## For the demo (Thursday 2026-11-27)

1. `demo_display.py replay --port COM5` takes about 7.5 minutes for the whole night. Use `--max-epochs 300`
   (~2.5 h of night, about 2 minutes) for a shorter run. If the board misbehaves, use `--port none`.
2. `demo_display.py live --source adc --port COM5` with the headband, **laptop on battery or through the USB
   isolator** (REQ-SAFE). Eyes closed should raise relative alpha within a few seconds.
3. Oura (task 5) is a separate panel still to come; it's blocked until the Oura developer app is registered.

## Next

| # | Task | Notes |
|---|---|---|
| 5 | Oura app and an Oura panel for the demo | Waiting on the Oura developer app registration (STATUS §4 Q3) |
| 7 | Wiring and bring-up per `docs/bringup.md` when the parts arrive (around 2026-11-26) | Then `live --source adc` |
