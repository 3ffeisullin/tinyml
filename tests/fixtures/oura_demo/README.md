# Oura demo nights (sample data, no personal data)

14 nights in Oura's stored format, built by `scripts/make_oura_demo.py` (code in `hub/oura_app/demo_data.py`).

- **Sleep stages** are real expert scoring from **Sleep-EDF** (PhysioNet, ODC-By 1.0): one night from each of
  subjects 0–13, mapped W → awake, N1/N2 → light, N3 → deep, REM → REM. So the nights come from 14 different
  people, not one person over two weeks.
- **Heart rate, HRV, breathing rate, scores and contributors are simulated** from those stages with a fixed seed.
  The scores are simple stand-ins, not Oura's formulas. Every record carries `"synthetic": true`.
- Nights 2026-11-11, -16 and -21 have a stretch of missing heart-rate/HRV values, as when the ring loses contact.

Use: `scripts/demo_display.py oura --demo` (display work, tests, slides, and the demo fallback).
Nothing from `data/oura/live/` goes here.
