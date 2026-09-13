"""Global keyboard shortcuts (work while another app is in front) via pynput.

macOS needs two permissions for this, granted per app (Terminal, or OutLoud.app):
System Settings -> Privacy & Security -> Accessibility, and -> Input Monitoring.
Without them the listener starts but hears nothing, so we check first and say so.
"""
from __future__ import annotations

import sys
import time
from typing import Callable, Dict, Optional, Tuple

DEFAULT_COMBOS: Dict[str, str] = {
    "read_selection": "<ctrl>+<alt>+r",
    "read_area": "<ctrl>+<alt>+a",
    "toggle": "<ctrl>+<alt>+p",
    "stop": "<ctrl>+<alt>+s",
}

LABELS = {
    "read_selection": "read the selected text",
    "read_area": "read a screen area",
    "toggle": "play / pause",
    "stop": "stop",
}


def combo_label(combo: str) -> str:
    """Human label for a pynput combo string, in the platform's own words."""
    key = combo.rsplit("+", 1)[-1].upper()
    if sys.platform == "darwin":
        return f"Control + Option + {key}"
    return f"Ctrl + Alt + {key}"


def mac_permissions() -> Tuple[bool, bool]:
    """(can listen, can post events). Both True on non-mac platforms."""
    if sys.platform != "darwin":
        return True, True
    try:
        import Quartz

        listen = bool(Quartz.CGPreflightListenEventAccess())
        post = bool(Quartz.CGPreflightPostEventAccess())
        return listen, post
    except Exception:
        return True, True  # cannot check: let pynput try


def request_mac_permissions() -> None:
    if sys.platform != "darwin":
        return
    try:
        import Quartz

        Quartz.CGRequestListenEventAccess()
        Quartz.CGRequestPostEventAccess()
    except Exception:
        pass


class Hotkeys:
    def __init__(self, dispatch: Callable[[str], None], combos: Optional[Dict[str, str]] = None) -> None:
        self.dispatch = dispatch
        self.combos = dict(combos or DEFAULT_COMBOS)
        self.listener = None

    def start(self) -> Tuple[bool, str]:
        """Returns (ok, message for the status bar)."""
        try:
            from pynput import keyboard
        except Exception as exc:
            return False, f"Global hotkeys unavailable (pynput not installed): {exc}"
        listen, post = mac_permissions()
        if not (listen and post):
            request_mac_permissions()
            return False, (
                "macOS needs permission for global hotkeys: System Settings > Privacy & Security > "
                "Accessibility AND Input Monitoring > enable this app, then tick Global hotkeys again."
            )
        mapping = {combo: (lambda name=name: self.dispatch(name)) for name, combo in self.combos.items()}
        try:
            self.listener = keyboard.GlobalHotKeys(mapping)
            self.listener.daemon = True
            self.listener.start()
            self.listener.wait()
            time.sleep(0.2)
            if not self.listener.is_alive():
                self.listener = None
                return False, "Global hotkeys could not start (the OS refused the keyboard hook)."
        except Exception as exc:
            self.listener = None
            return False, f"Global hotkeys could not start: {exc}"
        return True, "Global hotkeys on: " + ", ".join(
            f"{combo_label(c)} = {LABELS[n]}" for n, c in self.combos.items()
        )

    def stop(self) -> None:
        if self.listener is not None:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None


def copy_selection() -> None:
    """Ask the front app to copy its selection (Cmd+C on Mac, Ctrl+C elsewhere)."""
    from pynput.keyboard import Controller, Key

    kb = Controller()
    # The user is still holding the hotkey modifiers; release them so they do not
    # combine with the copy shortcut.
    for k in (Key.ctrl, Key.ctrl_l, Key.ctrl_r, Key.alt, Key.alt_l, Key.alt_r, Key.shift):
        try:
            kb.release(k)
        except Exception:
            pass
    time.sleep(0.08)
    modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
    with kb.pressed(modifier):
        kb.press("c")
        kb.release("c")
