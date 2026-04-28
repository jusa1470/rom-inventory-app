# RecordSync — Getting Started

## First time only

1. Double-click **RecordSync-Setup**
2. Create a master password (this is what you'll use to open the app)
3. Enter the Webami and Shopify credentials when prompted
   - You'll need to get these from whoever sent you this app
4. Done — credentials are saved to your system keychain, never to a file

## Every time after that

Just double-click **RecordSync**.

## If you need to re-enter credentials

Run **RecordSync-Setup** again and choose to overwrite when prompted.

## Notes

- Your credentials are stored in your OS keychain (same place as saved passwords
  in Safari/Chrome). They are not stored in any file and are not readable by
  other apps.
- The app will not work without running setup first.

# Running & Packaging RecordSync

## Running locally for development

### 1. Install dependencies

```bash
cd app
pip install -r requirements.txt
```

`requirements.txt` covers everything: fastapi, uvicorn, sqlalchemy, requests,
beautifulsoup4, lxml, keyring, apscheduler, pydantic.

### 2. First-time credential setup

Run the setup script once before starting the server. It stores everything in
your OS keychain — nothing is written to any file.

```bash
python setup.py
```

You'll be prompted to create a master password, enter Webami credentials, and
paste your Shopify Admin API token.

### 3. Start the server

```bash
python main.py
```

Then open **http://127.0.0.1:8000** in your browser. The app serves the
frontend from `static/` and the API under `/api/`.

### 4. Iterating on the frontend

The frontend is plain HTML/CSS/JS in `static/`. Edit `static/app.js` or
`static/index.css` and hard-refresh the browser (`Cmd+Shift+R` / `Ctrl+Shift+R`).
No build step needed.

To enable auto-reload of the Python backend during development:

```bash
uvicorn --app-dir backend main:app --reload --host 127.0.0.1 --port 8000
```

Note: `--reload` watches `.py` files only, not static files.

---

## Packaging as an executable

### Prerequisites

```bash
pip install pyinstaller
```

PyInstaller must be run on the **same OS** you're targeting. A Mac build runs
on Mac, a Windows build runs on Windows. There's no cross-compilation.

### Build

```bash
pyinstaller build.spec
```

Output is a folder at `dist/RecordSync/` containing two executables:

| File | Purpose |
|---|---|
| `RecordSync` (or `.exe`) | The main app — run this every time |
| `RecordSync-Setup` (or `.exe`) | One-time credential setup — run once per machine |

### What to send someone

Zip the entire `dist/RecordSync/` folder and send it. Tell them:

1. Run **RecordSync-Setup** first and enter the credentials you give them
2. After that, just run **RecordSync** — it opens a browser window automatically

### Auto-opening the browser

To make the packaged app open a browser tab automatically on launch, add these
two lines to `main.py` inside the lifespan startup block (after `init_db()`):

```python
import threading, webbrowser
threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
```

The 1.5 second delay gives uvicorn time to bind before the browser tries to connect.

### macOS note — Gatekeeper

The first time someone runs an unsigned app on macOS, Gatekeeper will block it
with "app can't be opened because it's from an unidentified developer."

They need to right-click → Open (not double-click) the first time, then click
Open in the dialog. After that it runs normally.

To avoid this entirely you'd need an Apple Developer certificate ($99/yr).

### Windows note — Defender SmartScreen

Same situation on Windows — SmartScreen will warn on first run. Click
"More info" → "Run anyway."

### Linux note — keyring backend

If the recipient is on Linux without a desktop session (headless server, WSL),
the keyring library needs a backend. They'll need either:

```bash
sudo apt install gnome-keyring   # GNOME
# or
pip install keyrings.alt         # file-based fallback (less secure but works anywhere)
```

---

## Troubleshooting

**`ModuleNotFoundError` after packaging** — add the missing module to
`hiddenimports` in `build.spec` and rebuild.

**Keychain prompt on every launch (macOS)** — the first time the app reads from
Keychain, macOS asks for permission. Click "Always Allow" and it won't ask again.

**Port 8000 already in use** — change the port in `main.py`:
```python
uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=False)
```