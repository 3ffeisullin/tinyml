# Demo runbook: Friday 2026-12-04

What to run, in what order, what to say, and what to do when something fails. Rehearsed on the laptop
on 2026-11-23 from `master` (`c970443`), Plan B end to end; results in [Rehearsal log](#rehearsal-log).

- **Plan A** (parts arrive Tuesday 12-01, brought up and dry-run by Thursday 12-03): replayed night on the board → **live EEG from the
  headband** → Oura screen.
- **Plan B** (bring-up or the Plan A dry run not finished by Thursday 12-03): the same, with the live view on the board's fake
  source instead of the headband.

Total about 12–15 min plus questions. One board, one COM port: the replay and the live view run **one
after the other**, never at the same time (switching between them needs nothing; rehearsed).

## Schedule

The demo moved from Friday 11-27 to Friday 12-04 (Farid, 2026-11-26) because the BioAmp EXG Pill and ADS1115
arrive on Tuesday 12-01.

| Day | What |
|---|---|
| Tue 12-01 | Parts arrive. Bring-up per [`docs/bringup.md`](bringup.md): wiring, ADS1115 found, measured sample rate, `PILL_GAIN` calibration, quality thresholds (step 7) |
| Wed 12-02 | First Plan A dry run with the headband (battery only, or the USB isolator); fix what it shows |
| Thu 12-03 | Day-before checklist below, one full timed dry run. **Decide Plan A or B by Thursday evening** |
| Fri 12-04 | Morning checklist, demo |

Plan B is rehearsed (2026-11-23) and needs nothing new, so it stays the fallback at every step.

## Safety first (REQ-SAFE-01..03), Plan A only

Electrodes on a person only when nothing connected to the person's circuit touches mains:

- **A projector or external monitor on the laptop counts as mains** (its HDMI/USB-C cable carries
  ground). With a projector connected, the XIAO goes through the **USB isolator**; no exceptions.
- Without a projector: laptop on battery, charger unplugged, nothing else plugged in; or the isolator.
- Electrodes off before plugging or unplugging anything.

Plan B has no electrodes and no restrictions.

## The day before (Thursday 12-03)

- [ ] `git checkout master && git pull`; `.\venv\Scripts\python.exe -m pytest` passes.
- [ ] Flash the exact build that will be shown:
      `& $cli upload --fqbn esp32:esp32:XIAO_ESP32S3 -p COM5 firmware\eeg_node` (`$cli` as in README).
- [ ] Laptop charged to 100 % (Plan A on battery: the live part runs on battery).
- [ ] Data cable (not a charge-only cable), USB isolator, headband, gel, wipes packed.
- [ ] One full dry run of this runbook, timed.
- [x] Oura segment shows Farid's nights (decided 2026-11-24); `--demo` is the fallback (segment 3).

## On the morning

1. Open the Oura phone app so the ring syncs last night (the scheduled pull runs at 09:30; or pull by hand):
   `.\venv\Scripts\python.exe -m hub.oura_app pull` → expect "1 new" for `sleep`.
   `.\venv\Scripts\python.exe -m hub.oura_app status` → "Signed in; access token valid for … h".
2. Close other apps, turn on Windows "Do not disturb", set display scaling so the window fits the projector.
3. Plug in the XIAO (data cable; isolator if Plan A with a projector). Check the port:
   `& $cli board list` → "COM5 … ESP32 Family Device". If it shows another COMx, use that below.
4. Board self-test (optional, 1 s): send `TEST` over the serial port (e.g. with `scripts/live_log.py`-style pyserial, or Arduino IDE Serial Monitor) → "FEATURE SUMMARY PASS" and "MODEL SUMMARY parity 5/5". After bring-up the boot log must say "ADC found at 0x48".
5. Warm-up run (also warms Python/TensorFlow start-up): `demo_display.py replay --port COM5 --max-epochs 20`,
   close it.

All commands below run from `C:\Users\ffeis\tinyml` with `.\venv\Scripts\python.exe scripts\demo_display.py …`.

## Running order

### 0. Opening (1 min)

A forehead EEG headband (BioAmp EXG Pill → ADS1115 → Seeed XIAO ESP32-S3) that stages sleep **on the
board**: a 6.3 KB int8 neural network running TensorFlow Lite Micro, 224 µs per inference. The laptop only
displays. Oura ring alongside for context. Hobby/research project, no medical claims (REQ-SAFE-04).

### 1. The board stages a night it has never seen (3–4 min)

```
demo_display.py replay --port COM5 --max-epochs 360        # 3 h of the night in ~3 min
```
(Full night: drop `--max-epochs`; 1,023 epochs take ~7.5 min, too long unless it runs while you talk.)

Say:
- This is a real night from Sleep-EDF (PhysioNet), subject 20, **held out**: not in the model's training set.
  The raw EEG streams to the XIAO over USB; the board filters it, computes 30 features, standardises them
  on the fly and runs the model; the laptop just draws what the board sends back.
- Top: the sleep experts' hypnogram, scored by hand. Middle: the board's stages as they arrive.
- **"XIAO = PC reference 100 %"**: the board's stages are identical to the Python reference, epoch for epoch.
  That's the engineering claim: the firmware is a faithful port.
- **Agreement with the experts ~67 % on this night**; cross-validated over 20 people the model scores
  76.8 % (macro F1 0.707, vs 0.680 for a random-forest baseline). One forehead channel; REM vs wake is the
  main confusion. ~286 ms of board time per 30 s epoch, so a whole night's staging is cheap.
- Bottom: relative band power per epoch, also from the board.

If asked about deep sleep: experts themselves agree on only ~67 % of deep-sleep epochs; per epoch our deep
sleep is near expert level (recall 0.80), per night it's off by ~25 min on average (`docs/deep-sleep.md`);
calibrated slow-wave features are the next step (REQ-FEAT-12).

### 2. Live signal (3–5 min)

Close the replay window first (same COM port).

**Plan A** (headband on, battery/isolator per Safety):
```
demo_display.py live --source adc --port COM5
```
- Eyes open 20 s, then eyes closed 20 s: **relative alpha rises with eyes closed** (the classic EEG demo).
- Blink or move: the peak-to-peak jumps and the banner turns **⚠ Check signal** with the reason; lift an
  electrode: **✕ Bad signal** within ~3 s. That's the signal-quality check the staging relies on.
- Stages start after a 5-minute warm-up (10 epochs for the running standardisation); start this view early
  if you want to show a stage.

**Plan B** (no sensor):
```
demo_display.py live --source fake --port COM5
```
- Same firmware path, fed by a 250 Hz timer replaying a test signal: the board's live windows match the
  PC reference ("Fake-source check PASS"), 250 Hz, 0 missed samples / I2C errors / overflows.
- The banner shows **⚠ Check signal: mains hum**. Say it before anyone asks: *the test signal carries
  60 Hz hum on purpose, and the quality check catches it* (the banner says so too).

### 3. Oura ring (2 min)

```
demo_display.py oura            # the ring's nights (Farid's data): the default
demo_display.py oura --demo     # fallback: 14 sample nights, Sleep-EDF expert stages, simulated heart rate/HRV
```
- Oura stages sleep from heart rate, HRV, movement and temperature, not EEG; light = N1 + N2. It's
  context and a weak reference (REQ-OURA-08: comparing it with the headband overnight is the next phase).
- Pulled automatically twice a day through the Oura API v2 (OAuth, tokens in Windows Credential Manager).
- **Farid's data may be shown** (his decision, 2026-11-24), so the plain `oura` view is the default. Use
  `--demo` (it says "Sample nights" in the subtitle) if the ring hasn't synced or the sign-in fails.
  For a slide: `demo_display.py oura --headless --save reports/oura_live_<day>.png` (may be committed).

### 4. Close (1 min)

Numbers: 6.3 KB model, 224 µs per inference, 956-byte arena; board = PC on 100 % of 1,023 epochs;
macro F1 0.707. Next: overnight recordings next to the ring (phase D), deep-sleep features, the hub
(InfluxDB/Grafana) after the demo.

## When something goes wrong

| Symptom | Do this |
|---|---|
| `could not open port COM5` / board not found | Close any other window using it (only one view at a time). Unplug/replug; `& $cli board list`; use the COMx it shows. Still nothing: data cable? |
| Replay window freezes or stops mid-night | Close it; rerun. Fallback: `replay --port none` plays the PC reference (same display, says so; starts in ~11 s) |
| Live view: "✕ No data from the board" | USB cable/isolator; close and restart the view; still nothing: unplug/replug the XIAO |
| Plan A: banner stays ✕ / mains hum high | Re-gel, press electrodes, shorten leads, move away from power cables; if it won't settle, switch to Plan B (`--source fake`) and say why |
| Plan A: no alpha rise | Common on the first try: longer eyes-closed (30 s), relax; or move on, the quality banner is the point |
| Oura: no new night | Ring didn't sync: open the Oura app and `hub.oura_app pull`; or show `--demo` |
| Oura: "not signed in" / AuthError | Don't log in live on the projector (browser sign-in). Show `--demo` |
| Window too big for the projector | Windows display scaling 100 %, or maximise the window (it re-flows) |
| Python start-up slow (first run ~10 s, TensorFlow) | Normal; the morning warm-up run avoids it |

## Rehearsal log

| Date | Build | What | Result |
|---|---|---|---|
| 2026-11-23 | `master` `c970443`, eeg_node flashed to the XIAO on COM5 | Replay, full night on the board | 1,023 epochs, board = PC 100.0 %, experts 67.0 %, 286 ms/epoch, **7 min 39 s** incl. start-up |
| 2026-11-23 | same | Replay, `--max-epochs 360` (3 h), right after a live session | board = PC 100.0 %, experts 66.9 %, **2 min 50 s**; switching live → replay needs nothing |
| 2026-11-23 | same | Live, fake source, 75 s | 249.99 Hz, 0/0/0, fake-source check PASS, banner ⚠ mains hum with the "expected" note |
| 2026-11-23 | same | Replay fallback `--port none`, 120 epochs | starts and finishes in ~11 s |
| 2026-11-23 | same | Oura screen, own data and `--demo` | ~2.5 s each; `--save` into `reports/` correctly refused for own data; token valid ~30 days |
| 2026-11-23 | same | On-board self-tests (`TEST` command over USB) | filters within 6.5e-08 of full scale, 0/20 features out of tolerance (worst 0.004 of tolerance), 17 µs/sample, 5.2 ms/window; model parity 5/5, 224 µs/inference, arena 956 bytes; boot reports "ADC NOT found at 0x48" (expected: no ADS1115 yet) |
| | | Plan A (headband) | first dry run Wed 12-02, after bring-up on Tue 12-01 |
