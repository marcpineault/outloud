# OutLoud

Reads PDFs and any text on your screen out loud. Mac and Windows. Free, works offline, and uses the voices already on your computer. Nothing is uploaded anywhere.

![OutLoud window](docs/screenshot.png)

## What it does

- **A PDF viewer that reads to you.** Pages scroll like a book. Press Play and it reads page after page, highlighting each sentence right on the page as it goes.
- **Click any sentence** to hear it from there. **Type a page number** at the top and press Enter to jump straight to it.
- **Scanned PDFs work too.** Pages without a text layer are read with the built-in OCR, and the highlighter still follows along.
- **Read anything on screen.** Select text in any app and press one shortcut, or drag a box over any part of the screen, even a picture of text.
- Pick a **voice**, set the **speed**, zoom the page.

## Install on a Mac (the easy way)

1. Download **OutLoud-mac-arm64.zip** from the [latest release](https://github.com/marcpineault/outloud/releases/latest) and unzip it.
2. Drag **OutLoud.app** into Applications and double-click it.
3. macOS will say it cannot check the app for malware, because it is not from the App Store. Click **Done**, open **System Settings > Privacy & Security**, scroll down and click **Open Anyway**. You only do this once.

   (Alternative for the terminal-minded: `xattr -dr com.apple.quarantine /Applications/OutLoud.app`)
4. The first time you use a feature, macOS asks for a permission. Say yes:
   - **Screen Recording** for reading a screen area or the whole screen.
   - **Accessibility** and **Input Monitoring** for the global hotkeys.

Intel Mac? Run from source (below), or build the app yourself with `pyinstaller packaging/OutLoud.spec`.

## Install on Windows

1. Download **OutLoud-windows-x64.zip** from the [latest release](https://github.com/marcpineault/outloud/releases/latest), unzip it anywhere.
2. Run **OutLoud.exe**. If SmartScreen complains, click **More info > Run anyway**.

Screen reading on Windows uses the OCR built into Windows 10/11 (English language pack). Voices come from Windows itself; add more under Settings > Time & Language > Speech.

## Using it

| Do this | To get |
|---|---|
| Open PDF… (or drop a PDF on the window) | The book view. Scroll with the wheel or trackpad, Page Up / Page Down, Home / End |
| Play | Reads from the page you are looking at, turning pages by itself |
| Click a sentence | Reads from that sentence (works while it is already reading, too) |
| Page box at the top, type 350, Enter | Jumps to page 350. Cmd/Ctrl G puts the cursor in the box |
| ◀ ▶ | Previous / next page |
| − + Fit width | Zoom. Cmd/Ctrl − / = / 0 do the same |
| Read from screen ▾ | Read clipboard, drag a box on the screen, or read the whole screen |
| Back to the PDF | After reading something from the screen, return to where you were |
| Space, Esc, ← → | Play / pause, stop, previous / next sentence |
| Voice, Speed | Any voice installed on your computer; 100 to 350 words per minute |

**Global hotkeys** (Read menu, or the switch at the top right) work while you are in any other app:

| Mac | Windows | Does |
|---|---|---|
| Control + Option + R | Ctrl + Alt + R | Read the text you have selected |
| Control + Option + A | Ctrl + Alt + A | Drag a box on screen and read it |
| Control + Option + P | Ctrl + Alt + P | Play / pause |
| Control + Option + S | Ctrl + Alt + S | Stop |

## Better voices (Mac)

The stock voices are fine; the downloadable ones are much better. System Settings > Accessibility > Spoken Content > System voice > Manage Voices… then download an English voice marked **Premium** or **Enhanced** (for example Ava, Zoe, Evan). They appear in OutLoud's Voice menu and are chosen by default once installed.

Siri voices cannot be used by apps, which is why "System default voice" can be silent if your Mac's system voice is a Siri voice. Pick a named voice instead.

## Run from source (any OS, and for AI agents)

Needs Python 3.9 or newer. With [uv](https://docs.astral.sh/uv/) installed, this is a one-liner (the first run downloads about 200 MB of libraries):

```
uvx --from git+https://github.com/marcpineault/outloud outloud
```

Or clone and run:

```
git clone https://github.com/marcpineault/outloud
cd outloud
uv run outloud            # or: pip install -e . && outloud
```

Mac users can also double-click `run-mac.command`; Windows users `run-windows.bat`.

Tests: `uv run pytest`. Build the app: `uv run --extra dev pyinstaller packaging/OutLoud.spec` (output in `dist/`). Pushing a tag like `v0.3.0` makes GitHub build both apps and publish a release.

## Troubleshooting

- **No sound on Mac.** Choose a named voice; see "Better voices" above. Check the volume and that the Mac is not muted.
- **"Read screen area" finds no text.** Grant Screen Recording to OutLoud (or to Terminal if you run from source), then try again. Larger text reads better than tiny text.
- **Hotkeys do nothing.** Grant Accessibility and Input Monitoring, then switch Global hotkeys off and on again. Running from source means the permission goes to your terminal app, not to OutLoud.
- **A page is skipped.** It has no text and no picture, or OCR found nothing on it; zoomed-out scans of tiny text are the usual cause.
- **Windows and OCR.** If the Windows build could not include the OCR engine, run from source and `pip install winocr`, or `pip install rapidocr-onnxruntime` for a self-contained engine.

Windows has not been tested by a human yet (built and unit-tested on GitHub's Windows runners only). Reports welcome.

## For developers and AI agents

Start with [AGENTS.md](AGENTS.md): what each file does, the rules of the codebase, how to test and release, and the backlog.

MIT licensed.
