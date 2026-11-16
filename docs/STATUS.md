# Project status and handoff log

Last updated: 2026-11-16 by Claude (cloud session)

This file is the shared state between the two places work happens. Read it
before starting, and update it before you stop.

## 1. Who works where

| Workspace | Good for | Can't do |
|---|---|---|
| **Claude, cloud session** (claude.ai chat) | Design docs, requirements, Python reference code and tests, decks and spreadsheets, Notion, opening PRs | Reach the laptop or the XIAO; download from PhysioNet; call the Oura API (both blocked by its network allowlist) |
| **Claude Code on Farid's Windows laptop** | Flashing and monitoring the XIAO, running scripts that download data (Sleep-EDF), Oura API sign-in and sandbox calls, anything that needs the local venv or COM ports | — |

**Rules for both**
- Work on a feature branch and open a pull request into `master`; Farid reviews and merges.
- Every change of state (something built, run, decided or blocked) gets a dated line in §6 in the same commit, and the table in §2 is updated.
- `docs/requirements.md` is the reference for what to build; when a requirement is met, set its Status to Done in that file.
- The Notion page "TinyML EEG — Project Status & Handoff" mirrors this file for reading away from the laptop. The cloud session keeps it in sync; Claude Code updates it too if the Notion connector is available there.

## 2. Current state

| Phase | Item | Status | Where |
|---|---|---|---|
| Setup | Toolchain smoke test (synthetic model on the XIAO) | Done 2026-11-05 | `scripts/smoke_test.py`, `firmware/eeg_smoke/` |
| A | Requirements | In review | PR #1, `docs/requirements.md` |
| A | Python reference features (filters, bands incl. sigma, skew, kurtosis, epochs) | In review, 30 tests pass in the cloud | PR #1, `eegml/`, `tests/` |
| A | Firmware test vectors | In review | PR #1, `tests/vectors/`, `firmware/test_vectors/` |
| A | Sleep-EDF baseline (REQ-ML-02) | **Not run**: needs the laptop (PhysioNet) | `scripts/sleep_edf_baseline.py` → `reports/` |
| A | Int8 sleep model + conversion report (REQ-ML-03) | Not started | — |
| B | Firmware: ADS1115 acquisition, filters, features, parity test | Not started; waits for parts | `firmware/eeg_node/` (to come) |
| C | Oura app (OAuth2, nightly pull, sandbox) | Not started; must run on the laptop | `hub/` (to come) |
| C | Hub stack (Mosquitto, ingest, InfluxDB, Grafana) | Not started | `hub/` (to come) |
| D | Overnight recording with Oura | Not started | — |

## 3. Laptop runtime environment

Known so far (from the 2026-11-05 setup and the EECS 635 lab sessions). Claude
Code: confirm each line, fix anything wrong, fill the blanks, and note the date.

| Item | Value | Confirmed |
|---|---|---|
| OS | Windows (PowerShell) | yes |
| Repo clone path | _unknown — fill in_ | |
| Python venv for this repo | `venv\` in the repo, Python 3.12.10 | 2026-11-05 |
| TensorFlow / MNE in that venv | 2.21.0 / 1.13.2 (see `requirements.lock.txt`) | 2026-11-05 |
| `pytest` in that venv | _not installed yet (added to requirements.txt in PR #1)_ | |
| Arduino IDE / ESP32 core / TFLite Micro lib | 2.3.10 / 3.3.12 / Chirale_TensorFlowLite 2.0.0 | 2026-11-05 |
| arduino-cli | `C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe` | 2026-11-05 |
| Board FQBN | `esp32:esp32:XIAO_ESP32S3` | 2026-11-05 |
| XIAO serial port | COM5 with a data cable (COM4 is a Bluetooth port; charge-only cables were the cause of earlier upload failures) | EECS 635 labs |
| Separate course setup (don't mix) | EECS 635 labs use PlatformIO (`C:\Users\ffeis\.platformio\penv\Scripts\pio.exe`, espressif32@6.8.0 → Arduino core 2.0.17) and a Lab 4 venv `l4-kws-local` (Python 3.12, TF 2.19.1) | EECS 635 labs |
| Docker Desktop (for the hub) | _unknown — fill in_ | |
| Sleep-EDF cache | `%USERPROFILE%\mne_data` (MNE default) | |

## 4. Open questions for Farid

1. Review PR #1's decisions (requirements §7): band edges, 29 windows per epoch, skew/kurtosis on the filtered signal.
2. Have the front-end parts been ordered, and when do they arrive? The funding deck assumed a demo on Fri 2026-11-20.
3. Oura developer app: registered yet? Needs an Oura account with an active membership for a Gen3+ ring.
4. Repository rename: GitHub still shows `3ffeisullin/tinyml` with default branch `master`.

## 5. Next tasks (in order)

| # | Task | Who | Requirement |
|---|---|---|---|
| 1 | Check out PR #1's branch, install requirements, run `pytest`, run the Sleep-EDF baseline (20 subjects), commit `reports/` to the branch | Claude Code | REQ-ML-01/02 |
| 2 | Fill in §3 (environment) | Claude Code | — |
| 3 | Merge PR #1 once tests and baseline are in | Farid | — |
| 4 | Train the first sleep model on device features, quantise to int8, write the conversion report | Claude Code or cloud | REQ-ML-03/04 |
| 5 | Oura app skeleton in `hub/oura_app/`, sandbox first | Claude Code | REQ-OURA-01..07 |
| 6 | Firmware `eeg_node`: parity test on the board using `firmware/test_vectors/` before any hardware is wired | Claude Code | REQ-FEAT-09 |
| 7 | ADS1115 acquisition once parts arrive | Claude Code | REQ-HW-*, REQ-ACQ-* |

## 6. Handoff log

Newest first. One line per change: date, who, what, where.

- 2026-11-16 · cloud · Coordination set up: this file, `CLAUDE.md`, README status section, Notion mirror page. Branch `feature/requirements-and-reference-features`.
- 2026-11-16 · cloud · PR #1 opened: requirements, `eegml` reference features, Sleep-EDF baseline script, test vectors, 30 tests (pass in the cloud). Baseline not run (PhysioNet blocked in the cloud).
- 2026-11-16 · cloud · Reviewed `3ffeisullin/EEG-Time-Series-Models` (Palma et al. 2024). Kept: per-session standardisation, HMM state features as a candidate. Dropped: maze movement features, the trained Keras models. Found the two groups were stored at different rates and lengths (128 Hz × 7 s vs 2000 Hz × up to 21 s).
- 2026-11-13 · cloud · Hardware switched to the 3.3 V design (Pill on XIAO 3V3, VREF divider on ADS1115 A1); parts list total $206.35.
- 2026-11-05 · Claude Code (laptop) · Repo created with the toolchain smoke test; synthetic int8 model ran on the XIAO.

## 7. Links

- Notion status mirror: https://app.notion.com/p/41a46e5740dc8194be90f034e4384471
- Repo: https://github.com/3ffeisullin/tinyml · PR #1: https://github.com/3ffeisullin/tinyml/pull/1
- HLD (Claude Docs): https://claude.ai/artifact/6HctXg8m9RzXcDUbJAaLzb
- Detailed architecture (Claude Docs): https://claude.ai/artifact/6cdjSeZAPa5Gm7W7fLyGn6 · Notion mirror: https://app.notion.com/p/40d46e5740dc81068087e5ae23b0a104
- Front-end wiring: https://claude.ai/artifact/4ryjkqvAe9pjtotNki54dA
- Parts spreadsheet: https://claude.ai/artifact/UawZz9g3ivntLbPQsez2Xj
- Reference project: https://github.com/3ffeisullin/EEG-Time-Series-Models (copy of GabrielRPalma/UnderstandingLearningWithML)
