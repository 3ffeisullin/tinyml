# Instructions for Claude Code in this repository

This repo is the EEG sleep and brainwave monitor: a BioAmp EXG Pill + ADS1115 +
Seeed XIAO ESP32-S3 wearable, a Python reference pipeline, and a hub with an
Oura API v2 integration. Work is shared between a Claude cloud session
(claude.ai) and you, on Farid's Windows laptop.

## Before you start, every session
1. `git fetch` and read `docs/STATUS.md`: current state, laptop environment, next tasks, handoff log.
2. Read `docs/requirements.md` for anything you build; cite requirement IDs in commits.

## Before you stop, every session
1. Add a dated line to `docs/STATUS.md` §6 (newest first) saying what changed, and update §2, §3, §4 and §5 as needed.
2. If you met a requirement, set its Status in `docs/requirements.md`.
3. Commit on a feature branch, push, and open or update a PR into `master`. Don't merge; Farid merges.
4. If the Notion connector is available, mirror the change on the Notion page "TinyML EEG — Project Status & Handoff" (https://app.notion.com/p/41a46e5740dc8194be90f034e4384471). If not, say so in the log line; the cloud session will sync it.

## Environment (Windows, PowerShell)
- Use this repo's venv: `.\venv\Scripts\python.exe` (Python 3.12). Don't use the EECS 635 course setups (PlatformIO, `l4-kws-local`).
- Firmware builds use arduino-cli with ESP32 core 3.3.12 and FQBN `esp32:esp32:XIAO_ESP32S3`; the command lines are in README.md. The XIAO is usually COM5; COM4 is Bluetooth.
- Record any environment fact you discover or change in `docs/STATUS.md` §3.

## Code rules
- `eegml/config.py` holds every signal-processing parameter; the firmware must use the same values.
- After any change under `eegml/`, run `scripts/export_test_vectors.py` and `python -m pytest`, and commit the regenerated vectors.
- Never commit data downloads (`data/`), tokens or secrets. Oura OAuth client ID/secret go in a local `.env` that is git-ignored.

## Safety (REQ-SAFE-01..03)
Never suggest a test with electrodes on a person while the board is connected to
anything mains-powered. USB debugging with electrodes attached only through the
USB isolator or a laptop running on battery.
