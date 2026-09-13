# Working on OutLoud (for AI agents and humans)

OutLoud is a small desktop app that reads PDFs and on-screen text aloud. Mac is the priority; Windows must keep working. Everything runs offline with the voices already on the computer.

## Rules

1. **Offline only.** No cloud speech, no cloud OCR, no telemetry. If a feature needs the internet, it does not belong here.
2. **Mac first, never break Windows.** Anything platform specific goes behind a `sys.platform` check with a working fallback or a clear error message the user can act on.
3. **Python 3.9 syntax.** `from __future__ import annotations`, `Optional[X]` not `X | None` at runtime, no `match`. The app runs on whatever Python the user has.
4. **Stay light.** Tkinter (ships with Python), PyMuPDF, Pillow, pynput, pyobjc Vision/Quartz on Mac, pyttsx3 on Windows. Heavy optional engines (RapidOCR, Tesseract) are detected, never required.
5. **Never fail silently.** Every backend raises a typed error with install help; the UI shows it in the status bar or a dialog.
6. **Close the loop.** Run `pytest` before saying anything works. On a Mac also run `python -m outloud --selftest` (builds the whole window hidden and lists engines).

## Map

```
src/outloud/
  app.py        Tk window, buttons, event polling, sources (PDF / clipboard / screen), hotkey actions
  reader.py     playback thread: speaks chunks one by one, pause/jump/stop, posts events to a queue
  textsplit.py  normalize PDF text into paragraphs; split into sentence chunks with offsets
  tts.py        speech backends: macOS `say`, Windows pyttsx3 (SAPI5) / PowerShell fallback, espeak; default-voice pick
  ocr.py        OCR backends: Apple Vision, Windows OCR (winocr), RapidOCR, Tesseract; row grouping
  capture.py    screenshot helpers (screencapture on Mac, ImageGrab elsewhere) + drag-a-box overlay
  pdf.py        PyMuPDF wrapper: page text in reading order, scanned-page detection, page render for OCR
  hotkeys.py    pynput global hotkeys, macOS permission preflight, simulate copy for "read selection"
  config.py     JSON settings in the platform's app-support folder
tests/          pytest; real `say` to a file, real Apple Vision on a rendered image, fake TTS for the reader
packaging/      PyInstaller spec, icon generator and icons
.github/workflows/build.yml   tests + PyInstaller on macOS and Windows; tag v* publishes a release
run-mac.command, run-windows.bat   double-click launchers for running from source
```

## How the pieces talk

- The UI never speaks directly. `App` builds `Chunk`s from the Text widget content (`textsplit.split_sentences`), hands them to `Reader.load`, then calls `play/pause/seek/stop`.
- `Reader` runs one worker thread. It calls `backend.speak(chunk)` which blocks per sentence; `pause`/`seek`/`stop` call `backend.stop()` to kill the current utterance. An interrupted sentence is re-spoken from its start on resume.
- Progress comes back as tuples on a `queue.Queue` that Tk polls every 50 ms (`App._poll_events`). Never touch Tk widgets from the worker thread.
- Global hotkeys fire on pynput's thread. Keyboard simulation (copy) happens there; the UI action is queued as `("hotkey", name)`.
- Chunk offsets index the exact string in the Text widget. The widget is loaded with `textsplit.normalize(text)`; user edits are re-chunked on the next Play. Highlighting uses `1.0+{start}c` indices.

## Things learned the hard way

- On macOS the *system* voice is often a Siri voice. `say` cannot use it and emits 5 ms of silence. `tts.pick_default_voice` therefore prefers a Premium/Enhanced en_US voice, then Samantha. Do not default to "system voice" on Mac.
- `say -f -` reads the sentence from stdin; passing text as an argument breaks on sentences that start with `-`.
- Pillow's `ImageGrab.grab(bbox)` on macOS downsamples Retina captures to point size, which hurts OCR. `capture.grab_region` calls `screencapture -R` directly instead.
- The region overlay is an `overrideredirect` Toplevel with `-alpha 0.35` (verified on macOS 15). A true `-fullscreen` Toplevel triggers the Spaces animation.
- `screencapture` without Screen Recording permission returns the wallpaper only, so OCR finds nothing. The status message tells the user what to grant.
- pynput's listener on macOS starts "successfully" even without permission and just hears nothing. `hotkeys.mac_permissions` preflights with `CGPreflightListenEventAccess` / `CGPreflightPostEventAccess`.
- PyInstaller: the `.app` is unsigned. Users need Privacy & Security > Open Anyway once. Signing/notarizing needs an Apple Developer account (not set up).

## Testing and releasing

```
uv sync --extra dev                # or: pip install -e ".[dev]"
uv run pytest -q                   # 19 tests, ~5 s, no audio plays (say writes to a file)
uv run python -m outloud --selftest
uv run pyinstaller --noconfirm packaging/OutLoud.spec   # dist/OutLoud.app or dist/OutLoud/
```

Release: bump `version` in `pyproject.toml`, `src/outloud/__init__.py` and `packaging/OutLoud.spec`, commit, `git tag v0.x.y && git push --tags`. The workflow builds both platforms and attaches the zips to a GitHub Release.

Status as of 2026-09-13: developed and tested on an Apple Silicon Mac (macOS 15.6). Windows path is written to the documented APIs and unit-tested on GitHub's Windows runner, not yet used by a person.

## Backlog (good next tasks)

- Gapless playback on Mac: pre-synthesize the next sentence with `say -o` and play with `afplay` so there is no pause between sentences.
- Neural voices offline via Piper (piper-tts) as an optional backend; bundle one English voice.
- Run OCR off the Tk thread with a "Reading…" indicator (a full-screen capture takes ~1 s).
- Multi-monitor region capture (the overlay covers the primary display only).
- Drag and drop a PDF onto the window (tkinterdnd2, or the `tk::mac::OpenDocument` path already works for Finder "Open with").
- Remember the last page per PDF.
- Windows: a human test pass; confirm winocr installs on the CI Python, otherwise vendor RapidOCR into the Windows build.
- Code signing and notarization for a friction-free Mac install.
