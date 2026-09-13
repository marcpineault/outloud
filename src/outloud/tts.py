"""Text-to-speech backends.

Each backend speaks ONE chunk of text, blocking until it is done, and can be
interrupted from another thread with ``stop()``. Everything is offline and uses
the voices already installed on the computer:

* macOS   -> the ``say`` command (system voices, including Enhanced/Premium ones)
* Windows -> pyttsx3 over SAPI5, falling back to PowerShell's System.Speech
* Linux   -> espeak-ng / espeak if present (bonus, untested)
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Voice:
    id: str
    name: str
    lang: str = ""


class TTSError(RuntimeError):
    pass


class Backend:
    name = "base"

    def voices(self) -> List[Voice]:
        return []

    def speak(self, text: str, voice: Optional[str], rate_wpm: int) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        pass


class _SubprocessBackend(Backend):
    """Shared plumbing: run one process per chunk, terminate it on stop()."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def _run(self, cmd: List[str], stdin_text: str) -> None:
        with self._lock:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
            self._proc = proc
        try:
            _, err = proc.communicate(stdin_text.encode("utf-8"))
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
        # Negative return codes mean we terminated it on purpose.
        if proc.returncode and proc.returncode > 0 and err:
            raise TTSError(err.decode("utf-8", errors="replace").strip())

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass


_SAY_VOICE_LINE = re.compile(
    r"^(?P<name>.+?)\s+(?P<lang>[a-z]{2,3}[_-][A-Za-z]{2,}(?:[_-][A-Za-z0-9]+)*)\s+#\s*(?P<sample>.*)$"
)


def parse_say_voices(output: str) -> List[Voice]:
    voices = []
    for line in output.splitlines():
        m = _SAY_VOICE_LINE.match(line.strip())
        if m:
            voices.append(Voice(m.group("name"), m.group("name"), m.group("lang")))
    return voices


class MacSayBackend(_SubprocessBackend):
    name = "macos-say"

    def __init__(self) -> None:
        super().__init__()
        self._voices: Optional[List[Voice]] = None

    def voices(self) -> List[Voice]:
        if self._voices is None:
            try:
                out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=20).stdout
            except (OSError, subprocess.TimeoutExpired):
                out = ""
            self._voices = parse_say_voices(out)
        return self._voices

    def speak(self, text: str, voice: Optional[str], rate_wpm: int, out_file: Optional[str] = None) -> None:
        cmd = ["say", "-r", str(int(rate_wpm)), "-f", "-"]
        if voice:
            cmd += ["-v", voice]
        if out_file:
            cmd += ["-o", out_file]
        self._run(cmd, text)


class Pyttsx3Backend(Backend):
    """Windows SAPI5 through pyttsx3. The engine is created lazily per thread (COM rule)."""

    name = "pyttsx3"

    def __init__(self) -> None:
        self._engine = None
        self._thread_id: Optional[int] = None

    def _engine_for_this_thread(self):
        import pyttsx3  # imported lazily: only present on Windows installs

        if self._engine is None or self._thread_id != threading.get_ident():
            self._engine = pyttsx3.init()
            self._thread_id = threading.get_ident()
        return self._engine

    def voices(self) -> List[Voice]:
        eng = self._engine_for_this_thread()
        out = []
        for v in eng.getProperty("voices"):
            langs = getattr(v, "languages", None) or []
            lang = ",".join(str(x) for x in langs)
            out.append(Voice(v.id, v.name, lang))
        return out

    def speak(self, text: str, voice: Optional[str], rate_wpm: int) -> None:
        eng = self._engine_for_this_thread()
        if voice:
            eng.setProperty("voice", voice)
        eng.setProperty("rate", int(rate_wpm))
        eng.say(text)
        eng.runAndWait()

    def stop(self) -> None:
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass


class PowerShellBackend(_SubprocessBackend):
    """Fallback for Windows when pyttsx3 is missing: System.Speech via PowerShell."""

    name = "windows-powershell"
    _PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]

    def voices(self) -> List[Voice]:
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | "
            "ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture }"
        )
        try:
            out = subprocess.run(self._PS + [script], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        voices = []
        for line in out.splitlines():
            if "|" in line:
                name, lang = line.strip().split("|", 1)
                voices.append(Voice(name, name, lang))
        return voices

    def speak(self, text: str, voice: Optional[str], rate_wpm: int) -> None:
        rate = max(-10, min(10, round((int(rate_wpm) - 175) / 17.5)))
        select = f"$s.SelectVoice('{voice}'); " if voice else ""
        script = (
            "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Rate = {rate}; {select}"
            "$s.Speak([Console]::In.ReadToEnd())"
        )
        self._run(self._PS + [script], text)


class EspeakBackend(_SubprocessBackend):
    name = "espeak"

    def __init__(self, exe: str) -> None:
        super().__init__()
        self.exe = exe

    def speak(self, text: str, voice: Optional[str], rate_wpm: int) -> None:
        cmd = [self.exe, "-s", str(int(rate_wpm)), "--stdin"]
        if voice:
            cmd += ["-v", voice]
        self._run(cmd, text)


def pick_default_voice(voices: List[Voice]) -> Optional[str]:
    """A voice that is known to work when the user has not chosen one.

    On macOS the *system* voice is often a Siri voice, which ``say`` cannot use:
    it produces silence. So prefer a downloaded Premium/Enhanced English voice,
    then Samantha, then any English voice. Other platforms: system default.
    """
    if sys.platform != "darwin" or not voices:
        return None
    english = [v for v in voices if v.lang.lower().startswith("en")]
    for quality in ("premium", "enhanced"):
        for v in english:
            if quality in v.name.lower() and v.lang == "en_US":
                return v.id
    for v in english:
        if v.name == "Samantha":
            return v.id
    return english[0].id if english else None


def get_backend() -> Backend:
    if sys.platform == "darwin":
        return MacSayBackend()
    if sys.platform == "win32":
        try:
            import pyttsx3  # noqa: F401

            return Pyttsx3Backend()
        except Exception:
            return PowerShellBackend()
    for exe in ("espeak-ng", "espeak"):
        if shutil.which(exe):
            return EspeakBackend(exe)
    raise TTSError("No text-to-speech engine found on this computer.")
