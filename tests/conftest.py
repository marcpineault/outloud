"""Test session setup: Qt offscreen, and Qt loaded before MuPDF (Windows crashes otherwise)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PySide6.QtCore  # noqa: E402,F401  (must come before any pymupdf import)
