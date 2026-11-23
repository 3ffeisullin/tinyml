# Front-end bring-up checklist (task 7)

For the day the BioAmp EXG Pill and ADS1115 arrive (due around 2026-11-26; demo 2026-11-27). The firmware
(`firmware/eeg_node`, task 7a) and the logging script (`scripts/live_log.py`) are ready; this list
takes the hardware from bag to live signal in an order where each step isolates one thing.
Requirement IDs refer to `docs/requirements.md`.

## Safety first (REQ-SAFE-01..03)

- **No electrodes on a person while anything touches mains.** With electrodes on a person: the XIAO runs from
  its LiPo with USB unplugged, **or** USB goes through the USB isolator, **or** the laptop runs on battery
  with its charger unplugged (and nothing else, e.g. a monitor, plugged into the laptop).
- Steps 1–5 below use no electrodes on anyone.
- The firmware can't yet enforce REQ-SAFE-02 (refuse to record with USB VBUS present): the design has no
  VBUS sense pin yet. Until it does, this checklist is the control.

## 0. Before soldering

- [ ] Confirm the XIAO pinout against the board in hand: D4 = GPIO5 (SDA), D5 = GPIO6 (SCL), D1 = GPIO2
      (ALERT/RDY) (REQ-HW-03).
- [ ] Check the Pill's supply rating. The vendor docs list 5 V operation; our design runs it from 3.3 V
      (REQ-HW-01). Step 3 measures whether that works.

## 1. Wiring (REQ-HW-01..03)

| From | To | Note |
|---|---|---|
| XIAO 3V3 | ADS1115 VDD, Pill VCC, R1 top | everything on 3.3 V |
| XIAO GND | ADS1115 GND, ADDR, Pill GND, R2 bottom, C1 | ADDR to GND → address 0x48 |
| XIAO D4 (GPIO5) | ADS1115 SDA | breakout boards usually have pull-ups; if not, 4.7 kΩ to 3V3 |
| XIAO D5 (GPIO6) | ADS1115 SCL | same |
| XIAO D1 (GPIO2) | ADS1115 ALERT/RDY | open-drain; the firmware enables the internal pull-up |
| Pill OUT | ADS1115 A0 | |
| R1 = R2 = 10 kΩ divider midpoint, C1 = 100 nF to GND | ADS1115 A1 | VREF ≈ 1.65 V |

## 2. Board finds the ADC

- [ ] Flash `firmware/eeg_node` (README commands). The boot log ends with `ADC found at 0x48` and `READY`.
      `NOT found`: check SDA/SCL swap, pull-ups, 3V3 and GND.

## 3. Resting levels (multimeter, no electrodes)

- [ ] VREF on A1 ≈ 1.65 V.
- [ ] Pill OUT at rest, inputs shorted together: note the voltage. It should sit near 1.65 V; the differential
      range is ±2.048 V around A1. If it sits far off, use the fallback: `--mode adc-se` (single-ended A0, ±4.096 V)
      (REQ-HW-02).

## 4. Shorted-input noise and sample rate (REQ-HW-02 test 1, REQ-ACQ-02)

- [ ] Pill inputs shorted together (no electrodes):
      `.\venv\Scripts\python.exe scripts\live_log.py --mode adc --seconds 120 --log data\bringup_shorted.txt`
- [ ] `STAT`: `missed 0`, `i2c_errors 0`, `queue_full 0`. Note the measured **rate**: the ADS1115's internal
      oscillator is ±10 %, so it may read 225–275 Hz instead of 250. Write it in `docs/STATUS.md` §3. If it's off by
      more than ~1 %, band edges shift by the same fraction; we'll then either pace sampling from the XIAO
      (single-shot conversions on a timer) or correct `EEG_FS`.
- [ ] Peak-to-peak and band powers are the noise floor; keep the log for comparison.

## 5. Test tone and gain calibration (REQ-HW-02 test 2, REQ-ACQ-01)

- [ ] **Bench only, no electrodes on a person:** the signal generator is usually mains-powered.
- [ ] Target ≈ 100 µV peak-to-peak at 10 Hz at the Pill inputs (a strong alpha rhythm). Use a **signal generator**:
      a phone tone app is unreliable here, because headphone outputs roll off below ~20 Hz.
      Generator **100 mV p-p, 10 Hz sine** → **100 kΩ** in series → Pill input (+); **100 Ω** across the Pill inputs;
      generator ground → Pill input (−) and reference. The divider is ≈ 1/1,000, giving ≈ 100 µV p-p (A ≈ 50 µV).
      Trust the generator's display over a multimeter (many meters misread AC at 10 Hz). Log 60 s.
- [ ] The alpha band (8.5–11.5 Hz) dominates. With this pipeline's normalisation, band power is mean square ×
      NFFT/2, so a sine of amplitude A gives P = 256 × A²/2 (checked: 20 µV → P ≈ 51,200, log10 ≈ 4.71).
      Measured amplitude **A = √(P / 128) µV**, with P = 10^(logp_alpha) from the `W` lines.
- [ ] Gain calibration: new `PILL_GAIN` = 1000 × (measured amplitude ÷ applied amplitude). Set it in
      `eegml/config.py`, run `scripts/export_test_vectors.py` and `python -m pytest`, reflash, re-check within ±10 %
      (REQ-ACQ-01). Staging doesn't depend on this; absolute µV readouts and clip thresholds do.

## 6. On a person (battery or isolator only, see Safety)

- [ ] Electrodes: Fp1 (forehead, left) and mastoid, gel, skin prepared; the Pill's reference as wired.
- [ ] `live_log.py --mode adc --seconds 120`: eyes open 30 s, closed 30 s, repeated. **Eyes closed should raise
      relative alpha** (the classic demo signal). Blinks show as large peak-to-peak in eyes-open windows.
- [ ] Mains ratio (`line_ratio`) stays low; if not, shorten leads and move away from mains cables.

## Already verified without hardware (task 7a, 2026-11-22)

`LIVE FAKE` runs the same core-0 task and queue at 250 Hz from a timer. On the XIAO (335 s, log
`reports/xiao_live_fake_2026-11-22.txt`): 83,751 samples at 250.00 Hz, 0 missed samples, I2C errors or queue
overflows, and the first 11 live windows match Python's reference features (worst 0.4 % of tolerance). What
remains to be proved with the parts: the I2C reads, the ALERT/RDY interrupt and the actual rate.
