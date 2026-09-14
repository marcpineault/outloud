# Working on OutLoud (for AI agents and humans)

OutLoud is a small desktop app: a PDF viewer that reads the document aloud and highlights the sentence on the page, plus "read anything on my screen". Mac is the priority; Windows must keep working. Everything runs offline with the voices already on the computer.

## Rules

1. **Offline only.** No cloud speech, no cloud OCR, no telemetry. If a feature needs the internet, it does not belong here.
2. **Mac first, never break Windows.** Anything platform specific goes behind a `sys.platform` check with a working fallback or a clear error message the user can act on.
3. **Python 3.9 syntax.** `from __future__ import annotations`, `Optional[X]` not `X | None` at runtime, no `match`. The app runs on whatever Python the user has.
4. **Stay light.** PySide6-Essentials (the UI), PyMuPDF (PDF), Pillow, pynput, pyobjc Vision/Quartz on Mac, pyttsx3 on Windows. Heavy optional OCR engines (RapidOCR, Tesseract) are detected, never required. Do not add QtWebEngine, QtPdf or numpy.
5. **PyMuPDF only on the GUI thread.** It is not thread-safe. The viewer stays smooth by rendering only visible pages, two at a time on a short timer, and caching the pixmaps.
6. **Never fail silently.** Every backend raises a typed error with install help; the UI shows it in the status label or a dialog.
7. **Close the loop.** Run `pytest` before saying anything works. On a Mac also run `python -m outloud --selftest` (builds the whole window offscreen and lists engines) and look at `python -m outloud --screenshot out.png`.

## Map

```
src/outloud/
  app.py        Qt main window: toolbars, page box, stacked PDF view / text panel, sources, hotkey actions, event polling
  viewer.py     PdfViewer(QAbstractScrollArea): continuous layout, fit-width zoom, lazy Retina rendering, highlights, click -> page point
  pdf.py        PdfDocument (PyMuPDF) + PageText: words with boxes -> text -> sentence chunks -> boxes per chunk; scanned-page detection
  reader.py     playback thread: speaks chunks one by one, pause/jump/stop, posts events to a queue
  textsplit.py  normalize text into paragraphs; split into sentence chunks with offsets
  tts.py        speech backends: macOS `say`, Windows pyttsx3 (SAPI5) / PowerShell fallback, espeak; default-voice pick
  ocr.py        OCR engines returning lines WITH boxes: Apple Vision, Windows OCR (winocr), RapidOCR; Tesseract text-only; layout_lines
  capture.py    Qt RegionSelector overlay + screenshot helpers (screencapture on Mac, QScreen.grabWindow elsewhere)
  hotkeys.py    pynput global hotkeys, macOS permission preflight, simulate copy for "read selection"
  config.py     JSON settings in the platform's app-support folder
tests/          pytest (offscreen Qt); real `say` to a file, real Apple Vision on a rendered image, fake TTS for the reader, viewer geometry
packaging/      PyInstaller spec, icon generator and icons
.github/workflows/build.yml   tests + PyInstaller on macOS and Windows; tag v* publishes a release
run-mac.command, run-windows.bat   double-click launchers for running from source
```

## How the pieces talk

- The UI never speaks directly. For a PDF page, `MainWindow._page_map(i)` builds a `PageText` (cached per page); its `chunks` go to `Reader.load`, then `play/pause/seek/stop`. `reading_page` remembers which page the reader holds.
- `Reader` runs one worker thread. `backend.speak(chunk)` blocks per sentence; `pause`/`seek`/`stop` call `backend.stop()` to kill the current utterance. An interrupted sentence is re-spoken from its start on resume.
- Progress comes back as tuples on a `queue.Queue` polled by a 50 ms QTimer (`_poll_events`). Never touch widgets from the worker thread. Global hotkeys fire on pynput's thread and are queued the same way.
- Highlighting: `PageText.rects_for_chunk(i)` gives one box per printed line (page points); `PdfViewer.set_highlight(page, rects)` draws them with a multiply blend and scrolls only if they are off screen. A click goes `PdfViewer.clicked(page, x, y)` -> `PageText.chunk_at_point` -> `Reader.play(index)`.
- `finished` on a page -> `start_reading_page(page + 1)`; pages with no text and no image are skipped; pages with an image and no text go through OCR (`ocr.recognize_lines` -> `layout_lines` -> `PageText.from_ocr_lines`) so the highlighter still works on scans.
- Clipboard / screen text is shown in `TextPanel` (QTextEdit); chunk offsets index the plain text set on it. Offsets are Python characters vs Qt UTF-16 units: identical unless the text has emoji.

## Things learned the hard way

- v0.1 used Tkinter. It could not show the actual pages sharply (Tk 8.6 draws images at 1 point per pixel, blurry on Retina) and had no document view, which users found unintuitive next to Preview. v0.2 moved to PySide6 with a custom viewer. QtPdf's QPdfView was considered and rejected: its page geometry is private, so highlights could not be placed reliably.
- On macOS the *system* voice is often a Siri voice. `say` cannot use it and emits 5 ms of silence. `tts.pick_default_voice` prefers a Premium/Enhanced en_US voice, then Samantha. Do not default to "system voice" on Mac.
- `say -f -` reads the sentence from stdin; passing text as an argument breaks on sentences that start with `-`.
- PyMuPDF `get_text("words")` returns boxes in the *unrotated* page space. Multiply by `page.rotation_matrix` to match the rendered (rotated) page; `pdf.py` does this and `tests/test_pdf.py` checks it.
- Viewer rendering: `get_pixmap` at `scale * devicePixelRatio`, then `QPixmap.setDevicePixelRatio(dpr)` gives crisp Retina pages. Keep the vertical scrollbar always on: with "as needed" the fit-to-width relayout oscillates.
- Pillow's `ImageGrab.grab(bbox)` on macOS downsamples Retina captures to point size, which hurts OCR. `capture.grab_region` calls `screencapture -R` directly instead.
- `screencapture` without Screen Recording permission returns the wallpaper only, so OCR finds nothing. The status message tells the user what to grant.
- pynput's listener on macOS starts "successfully" even without permission and just hears nothing. `hotkeys.mac_permissions` preflights with `CGPreflightListenEventAccess` / `CGPreflightPostEventAccess`.
- winocr on new Windows builds returns an `IAsyncOperation`, not a coroutine; `await` it inside an `async def`.
- PyInstaller: the `.app` is unsigned. Users need Privacy & Security > Open Anyway once. Signing/notarizing needs an Apple Developer account (not set up).

## Testing and releasing

```
uv sync --extra dev                # or: pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen uv run pytest -q     # 23 tests, ~8 s, no audio plays (say writes to a file)
uv run python -m outloud --selftest
uv run python -m outloud --screenshot docs/screenshot.png
uv run pyinstaller --noconfirm packaging/OutLoud.spec   # dist/OutLoud.app or dist/OutLoud/
```

Release: bump `version` in `pyproject.toml`, `src/outloud/__init__.py` and `packaging/OutLoud.spec`, commit, `git tag v0.x.y && git push --tags`. The workflow builds both platforms and attaches the zips to a GitHub Release.

Status as of 2026-09-13: v0.2.0 developed and tested on an Apple Silicon Mac (macOS 15.6). Windows path is written to the documented APIs and unit-tested on GitHub's Windows runner, not yet used by a person.

## Backlog (good next tasks)

- Gapless playback on Mac: pre-synthesize the next sentence with `say -o` and play with `afplay` so there is no pause between sentences.
- Neural voices offline via Piper (piper-tts) as an optional backend; bundle one English voice.
- Run OCR off the GUI thread with a progress indicator (a scanned page takes ~1 s; PyMuPDF rendering must stay on the GUI thread, the OCR itself can move).
- Two-column PDFs: word order follows the PDF's content stream, which is usually right; add a column-aware sort for the cases where it is not.
- Search inside the PDF; a thumbnails / outline sidebar; remember the last page per file.
- Text selection and copy on the page.
- Windows: a human test pass; confirm winocr keeps installing on the CI Python, otherwise vendor RapidOCR into the Windows build.
- Code signing and notarization for a friction-free Mac install; an Intel Mac build (GitHub runner label for Intel macOS, or a universal2 build).
