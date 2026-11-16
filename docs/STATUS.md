# Project status and handoff log

Last updated: 2026-11-16 by Claude (cloud session)

This file is the shared state between the two places work happens. Read it
before starting, and update it before you stop.

## 0. Resume here

- **master** is at `309a1bf` (PRs #1 and #2 merged 2026-11-16). 32 tests pass on the laptop.
- **Active branch:** `feature/int8-sleep-model` (draft PR #3). Its first commit records the merges (this update).
- **Next work:** task 4 in §5 (int8 sleep model), then task 5 (Oura app skeleton).
- **Waiting on Farid:** Docker Desktop install (needed before task 5b, the hub stack), parts order status, Oura developer app registration.

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
| A | Requirements | Done (merged 2026-11-16) | `docs/requirements.md` |
| A | Python reference features (filters, bands incl. sigma, skew, kurtosis, epochs) | Done (merged 2026-11-16); 32 tests pass on the laptop | `eegml/`, `tests/` |
| A | Firmware test vectors | Done (merged 2026-11-16) | `tests/vectors/`, `firmware/test_vectors/` |
| A | Sleep-EDF baseline (REQ-ML-02) | **Done 2026-11-16, PASS**: 20 subjects, device features macro F1 0.680 / acc 0.774 vs MNE-tutorial features 0.621 / 0.729 | `reports/sleep_edf_baseline.md` |
| A | Int8 sleep model + conversion report (REQ-ML-03/04) | **Next**: branch `feature/int8-sleep-model`, draft PR #3 | `scripts/train_sleep_model.py`, `reports/` (to come) |
| B | Firmware: ADS1115 acquisition, filters, features, parity test | Not started; waits for parts | `firmware/eeg_node/` (to come) |
| C | Oura app (OAuth2, nightly pull, sandbox) | Not started; must run on the laptop | `hub/` (to come) |
| C | Hub stack (Mosquitto, ingest, InfluxDB, Grafana) | Not started | `hub/` (to come) |
| D | Overnight recording with Oura | Not started | — |
| Team | VS Code workspace (extensions, tests, Run Tasks) and onboarding guide | Done (merged 2026-11-16); verified on the laptop | `.vscode/`, `docs/getting-started.md` |

## 3. Laptop runtime environment

Known so far (from the 2026-11-05 setup and the EECS 635 lab sessions). Claude
Code: confirm each line, fix anything wrong, fill the blanks, and note the date.

| Item | Value | Confirmed |
|---|---|---|
| OS | Windows (PowerShell) | yes |
| Repo clone path | `C:\Users\ffeis\tinyml` | 2026-11-16 |
| Python venv for this repo | `venv\` in the repo, Python 3.12.10 | 2026-11-16 |
| TensorFlow / MNE in that venv | 2.21.0 / 1.13.2 (see `requirements.lock.txt`) | 2026-11-16 |
| `pytest` in that venv | 9.2.0 (installed from requirements.txt) | 2026-11-16 |
| Arduino IDE / ESP32 core / TFLite Micro lib | 2.3.10 / 3.3.12 / Chirale_TensorFlowLite 2.0.0 | 2026-11-05 |
| arduino-cli | `C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe` | 2026-11-05 |
| Board FQBN | `esp32:esp32:XIAO_ESP32S3` | 2026-11-05 |
| XIAO serial port | COM5 with a data cable (COM4 is a Bluetooth port; charge-only cables were the cause of earlier upload failures) | EECS 635 labs |
| Separate course setup (don't mix) | EECS 635 labs use PlatformIO (`C:\Users\ffeis\.platformio\penv\Scripts\pio.exe`, espressif32@6.8.0 → Arduino core 2.0.17) and a Lab 4 venv `l4-kws-local` (Python 3.12, TF 2.19.1) | EECS 635 labs |
| Docker Desktop (for the hub) | **Not installed yet**; Farid decided to install it on this laptop (no `docker` command, no install folder, no winget entry as of 2026-11-16) | 2026-11-16 |
| Docker prerequisites | WSL 2 present and default; hardware virtualization enabled; RAM 13.9 GB (Docker minimum 4 GB) | 2026-11-16 |
| Disk space | C: 251.8 GB free of 474.7 GB. Estimated Docker need ~10–15 GB: Desktop ~2–3 GB, WSL 2 VM disk ~1–2 GB to start, hub images ~2–3 GB, InfluxDB data tens of MB, ~5 GB headroom. The VM disk grows without shrinking; reclaim with `docker system prune`. | 2026-11-16 |
| VS Code | 1.146.0 at `%LOCALAPPDATA%\Programs\Microsoft VS Code`; all recommended extensions installed (Python 2026.10.0, Pylance, Jupyter, C/C++, GitHub PRs, Claude Code, plus Python Environments). On first open the interpreter had to be set by hand: Python: Select Interpreter → Enter interpreter path → `C:\Users\ffeis\tinyml\venv\Scripts\python.exe`; the status bar then shows "venv (3.12.10)". | 2026-11-16 |
| Sleep-EDF cache | `%USERPROFILE%\mne_data\physionet-sleep-data` (MNE default; 20 nights, ~1 GB); per-subject features in `data\cache\sleep_edf\` (git-ignored) | 2026-11-16 |
| AVG antivirus HTTPS scanning | AVG Web Shield re-signs HTTPS, which breaks Python/MNE downloads (`CERTIFICATE_VERIFY_FAILED`). Fix: on this laptop's AVG version, Settings → General → Exceptions → Add exception, entered as `https://<host>/*` (other AVG versions put it under Core Shields → Web Shield → Exclusions). Excluded so far: `physionet.org`, `api.ouraring.com`, `cloud.ouraring.com`. Check with `openssl s_client -connect <host>:443 -servername <host>`; the issuer must not be AVG. If a host still fails, also try Core Shields → Web Shield → Exclusions (needed earlier for winget/tunnel). | 2026-11-16 |

## 4. Open questions for Farid

1. ~~Review PR #1's decisions (requirements §7)~~ Accepted by merging PR #1, 2026-11-16.
2. Have the front-end parts been ordered, and when do they arrive? The funding deck assumed a demo on Fri 2026-11-20.
3. Oura developer app: registered yet? Needs an Oura account with an active membership for a Gen3+ ring.
4. Repository rename: GitHub still shows `3ffeisullin/tinyml` with default branch `master`.
5. ~~Docker Desktop is not installed on the laptop, and the hub (Phase C, REQ-HUB-01) needs it. Install it on the laptop, or run the hub on the Raspberry Pi?~~ Decided 2026-11-16: install Docker Desktop on the laptop.

## 5. Next tasks (in order)

| # | Task | Who | Requirement |
|---|---|---|---|
| 1 | ~~Check out PR #1's branch, install requirements, run `pytest`, run the Sleep-EDF baseline (20 subjects), commit `reports/` to the branch~~ Done 2026-11-16 | Claude Code | REQ-ML-01/02 |
| 2 | ~~Fill in §3 (environment)~~ Done 2026-11-16 | Claude Code | — |
| 3 | ~~Merge PR #1, then PR #2~~ Done 2026-11-16 (Claude Code, with Farid's one-time approval) | Farid | — |
| 3a | ~~Run the new real-data test on the laptop: `python -m pytest tests/test_sleep_edf_real.py` should pass, not skip~~ Done 2026-11-16: passes | Claude Code | REQ-ML-01 |
| 4 | **Int8 sleep model.** New `scripts/train_sleep_model.py` reading the cached features in `data/cache/sleep_edf/` (no re-download): standardise features per subject (stands in for per-session calibration, REQ-FEAT-10); small dense network (input = current epoch's 30 features plus the previous 2 epochs', a few thousand parameters); same 5-fold leave-subjects-out split as the baseline, with the random forest as the bar to beat; post-training int8 quantisation with a representative set from training folds only; report float vs int8 accuracy, macro F1, per-stage recall, agreement (≥ 98 %), model bytes and an arena estimate in `reports/sleep_model.md`; export the int8 model to `firmware/eeg_node/sleep_model.h`. Tests for the windowing of neighbour epochs and the export. | Claude Code (laptop, has the data) | REQ-ML-03/04, FEAT-10 |
| 4b | Run the exported model on the XIAO with the `eeg_smoke` pattern (embedded test epochs, print arena used and µs per inference) | Claude Code | REQ-ML-04 |
| 5 | **Oura app skeleton** in `hub/oura_app/`: plain Python first (no Docker needed): OAuth2 sign-in with a localhost callback page, encrypted token file, nightly pull + 3-day re-pull, UTC conversion, 401/429 handling, sandbox mode; tests with mocked API responses. Client ID/secret in a git-ignored `.env`. | Claude Code | REQ-OURA-01..07 |
| 5b | Hub stack in Docker Compose (Mosquitto, ingest, InfluxDB, Grafana, Oura app) — **needs Docker Desktop installed** | Claude Code | REQ-HUB-01, OURA-08 |
| 6 | Firmware `eeg_node`: parity test on the board using `firmware/test_vectors/` before any hardware is wired | Claude Code | REQ-FEAT-09 |
| 7 | ADS1115 acquisition once parts arrive | Claude Code | REQ-HW-*, REQ-ACQ-* |

## 6. Handoff log

Newest first. One line per change: date, who, what, where.

- 2026-11-16 · cloud · PRs #1 and #2 merged into master (`0db9aa5`, `309a1bf`) by Claude Code with Farid's one-time approval; the "Farid merges" rule stands for future PRs. Phase A items and the VS Code workspace moved to Done. New branch `feature/int8-sleep-model` (draft PR #3) with §0 "Resume here" and detailed specs for tasks 4 (int8 model) and 5 (Oura app). Order agreed with Farid: task 4, then task 5; Docker Desktop install becomes necessary at task 5b.
- 2026-11-16 · Claude Code (laptop) · PR #2 verified on the laptop: `python -m pytest` 32 passed; `tests/test_sleep_edf_real.py` passes, not skipped (subject 0 → 841 epochs). Farid checked VS Code: Testing panel 32/32 green, and the "Python: run all tests" task ends with 32 passed. On first open VS Code reported "An Invalid Python interpreter is selected"; fixed via Enter interpreter path to the repo venv. Clicking the warning leads to "Create Environment"; cancel it with Esc (no `.venv` was created). That fix is now in `docs/getting-started.md` step 3. AVG: the General → Exceptions path (`https://<host>/*`) is what worked for physionet.org; Web Shield exclusions are kept as a fallback in §3 and the guide. Notion mirror updated.

- 2026-11-16 · cloud · PR #2 (stacked on PR #1): VS Code workspace (`.vscode/` recommended extensions, venv + pytest settings, Run Tasks for tests, vectors, baseline, firmware compile/upload/monitor) and `docs/getting-started.md` for new team members. Loader hardening after the channel-name bug: missing channel now raises with the available names instead of being skipped; only download errors skip a subject; EDF header warnings silenced; progress lines flush. New `tests/test_sleep_edf_real.py` runs on a cached real night (expects 841 epochs for subject 0) and skips elsewhere. Corrected the AVG exceptions path in §3. Design docs updated with the new band edges and the baseline result.
- 2026-11-16 · Claude Code (laptop) · Decision: the hub's Docker stack will run on the laptop; Farid is installing Docker Desktop. §3 now records disk (251.8 GB free on C:, ~10–15 GB needed), RAM and WSL 2 / virtualization readiness. If the installer or Docker Hub pulls fail with certificate errors, add those hostnames to AVG's exceptions (see §3).

- 2026-11-16 · Claude Code (laptop) · Sleep-EDF baseline run (REQ-ML-01/02): 20 subjects, 20,626 epochs, 5-fold leave-subjects-out random forest. Device pipeline accuracy 0.774 / macro F1 0.680 vs MNE-tutorial features 0.729 / 0.621 → REQ-ML-02 **PASS**. N1 recall is weak (0.20). Report in `reports/`. Notion mirror updated.
- 2026-11-16 · Claude Code (laptop) · Fixed two bugs found while running the baseline. `eegml/sleep_edf.py` looked up channel `EEG Fpz-Cz`, but MNE's `infer_types=True` renames it `Fpz-Cz`, so every subject was skipped. `scripts/sleep_edf_baseline.py` crashed when no subject loaded; it now exits 1 with "no subjects loaded". Regenerated test vectors differ from the cloud copies only by ~1e-11 float noise, so they were not re-committed. 30 tests pass.
- 2026-11-16 · Claude Code (laptop) · Blocker cleared: AVG Web Shield HTTPS scanning broke PhysioNet downloads (`CERTIFICATE_VERIFY_FAILED`). Farid added AVG exceptions (Settings → General → Exceptions, `https://<host>/*`) for `physionet.org`, `api.ouraring.com` and `cloud.ouraring.com`. §3 environment table filled in (repo path, pytest 9.2.0, Docker not installed).

- 2026-11-16 · cloud · Coordination set up: this file, `CLAUDE.md`, README status section, Notion mirror page. Branch `feature/requirements-and-reference-features`.
- 2026-11-16 · cloud · PR #1 opened: requirements, `eegml` reference features, Sleep-EDF baseline script, test vectors, 30 tests (pass in the cloud). Baseline not run (PhysioNet blocked in the cloud).
- 2026-11-16 · cloud · Reviewed `3ffeisullin/EEG-Time-Series-Models` (Palma et al. 2024). Kept: per-session standardisation, HMM state features as a candidate. Dropped: maze movement features, the trained Keras models. Found the two groups were stored at different rates and lengths (128 Hz × 7 s vs 2000 Hz × up to 21 s).
- 2026-11-13 · cloud · Hardware switched to the 3.3 V design (Pill on XIAO 3V3, VREF divider on ADS1115 A1); parts list total $206.35.
- 2026-11-05 · Claude Code (laptop) · Repo created with the toolchain smoke test; synthetic int8 model ran on the XIAO.

## 7. Links

- Notion status mirror: https://app.notion.com/p/41a46e5740dc8194be90f034e4384471
- Repo: https://github.com/3ffeisullin/tinyml · PR #1: https://github.com/3ffeisullin/tinyml/pull/1 · PR #2: https://github.com/3ffeisullin/tinyml/pull/2
- HLD (Claude Docs): https://claude.ai/artifact/6HctXg8m9RzXcDUbJAaLzb
- Detailed architecture (Claude Docs): https://claude.ai/artifact/6cdjSeZAPa5Gm7W7fLyGn6 · Notion mirror: https://app.notion.com/p/40d46e5740dc81068087e5ae23b0a104
- Front-end wiring: https://claude.ai/artifact/4ryjkqvAe9pjtotNki54dA
- Parts spreadsheet: https://claude.ai/artifact/UawZz9g3ivntLbPQsez2Xj
- Reference project: https://github.com/3ffeisullin/EEG-Time-Series-Models (copy of GabrielRPalma/UnderstandingLearningWithML)
