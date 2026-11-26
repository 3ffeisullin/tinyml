# Getting started (Windows, VS Code)

For team members joining the project. It takes about 30 minutes, most of it
installs. You don't need to know VS Code beforehand: the two features you'll
use most are the **Testing panel** and **Run Task**, both covered below.

## 1. Install once

| Tool | Where | Notes |
|---|---|---|
| Git | git-scm.com | Defaults are fine |
| Python 3.12 (64-bit) | python.org | Tick "Add python.exe to PATH". Use 3.12 to match the versions pinned in `requirements.lock.txt` |
| VS Code | code.visualstudio.com | Not "Visual Studio": that is a different, much larger product |
| Arduino IDE 2.x | arduino.cc | Only if you'll build firmware. Then in Boards Manager install **esp32 by Espressif 3.3.12**, and in Library Manager install **Chirale_TensorFlowLite 2.0.0** |

If your antivirus scans HTTPS (AVG does), downloads from Python can fail with
`CERTIFICATE_VERIFY_FAILED`. Add these as exceptions (in AVG: Settings →
General → Exceptions, entered as `https://<host>/*`): `physionet.org`,
`api.ouraring.com`, `cloud.ouraring.com`. If a host still fails, also try Settings →
Protection → Core Shields → Web Shield → Exclusions (that was needed earlier for other tools).

## 2. Get the code

You need access to the private GitHub repo `3ffeisullin/tinyml`; ask Farid.
In PowerShell:

```powershell
cd $HOME
git clone https://github.com/3ffeisullin/tinyml.git
cd tinyml
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. Open it in VS Code

1. **File → Open Folder…** and pick the `tinyml` folder (the repo itself, not its parent).
2. Click **Install** when VS Code offers the recommended extensions (Python, Jupyter, C/C++, GitHub Pull Requests, Claude Code, Serial Monitor).
   Serial Monitor talks to the XIAO (COM5, 115200 baud, line ending LF or CRLF; send `TEST` or `STAT`); close it before running
   `demo_display.py` or `replay_night.py`, which need the same COM port.
3. Check the bottom-right status bar shows **venv (3.12.x)**. On first open VS Code may warn
   **"An Invalid Python interpreter is selected"**. To fix it: Ctrl+Shift+P → **Python: Select Interpreter**
   → **Enter interpreter path…** → `C:\Users\<you>\tinyml\venv\Scripts\python.exe` (the `venv` folder
   inside your clone).
   **Careful:** don't click the warning itself. It can lead into a **"Create Environment"** prompt, which
   would make a second, empty `.venv` folder. If that prompt appears, press **Esc** to cancel it.

## 4. Everyday use

**Run the tests:** click the flask icon on the left (Testing), then the
double-play button. Green ticks mean everything passes; click a red cross to see
why it failed. One test is skipped until Sleep-EDF has been downloaded; that's
expected.

**Run Task:** Terminal → Run Task… lists the project's commands:

| Task | What it does |
|---|---|
| Python: run all tests | Same as the Testing panel, in a terminal |
| Python: export firmware test vectors | Run after changing anything in `eegml/` |
| Python: Sleep-EDF baseline (20 subjects) | Downloads ~1 GB the first time (~25 min), writes `reports/sleep_edf_baseline.md` |
| Python: toolchain smoke test | Rebuilds the demo model in `firmware/eeg_smoke/model.h` |
| Firmware: compile / upload / serial monitor | Builds and flashes a sketch to the XIAO; asks for the port (usually COM5; COM4 is Bluetooth). The first compile takes 10+ minutes |

**Git:** the Source Control icon (branch symbol) shows changed files. Write a
message and click Commit, then Sync. Always work on a branch, never directly on
`master`: click the branch name in the bottom-left status bar → "Create new
branch". Open pull requests from the GitHub icon on the left.

## 5. Project rules worth knowing on day one

- Read `docs/STATUS.md` first: what's done, what's next, and a log of every change.
- `docs/requirements.md` says what to build and how each piece is checked.
- Add a dated line to the log in `docs/STATUS.md` when you change something.
- **Safety:** never wear the electrodes while the board is connected to anything plugged into the wall. Use battery only, or the USB isolator.

## On a Mac or Linux

Everything works the same except paths: the venv's Python is
`venv/bin/python`, and in `.vscode/settings.json` change
`python.defaultInterpreterPath` and `tinyml.arduinoCli` (run `which arduino-cli`
after installing it from arduino.cc). The tasks use Windows paths, so on a Mac
run the same commands in the terminal instead.
