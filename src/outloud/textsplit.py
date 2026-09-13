"""Turn raw text (from a PDF, the clipboard or OCR) into speakable sentence chunks.

Chunks carry character offsets into the text they were cut from, so the UI can
highlight the sentence being read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "vs", "etc", "e.g", "i.e",
    "no", "inc", "ltd", "co", "corp", "fig", "vol", "approx", "dept", "est", "min", "max",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "u.s", "u.k", "a.m", "p.m", "ph.d", "b.c", "a.d",
}

# Sentence-ending punctuation, optional closing quotes/brackets, then whitespace.
_BOUNDARY = re.compile(r"([.!?…]+[\"'”’)\]]*)(\s+)")


@dataclass
class Chunk:
    text: str
    start: int  # character offset into the source text
    end: int


def normalize(text: str) -> str:
    """Join hard line breaks into paragraphs, fix hyphenation, squeeze whitespace.

    Paragraphs stay separated by one blank line. Single newlines inside a
    paragraph (the way PDFs and OCR deliver text) become spaces.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n\n")
    text = text.replace("­", "")  # soft hyphen
    text = re.sub(r"(\w)-\n\s*(\w)", r"\1\2", text)  # inter-\nnational -> international
    paragraphs = re.split(r"\n\s*\n", text)
    out = []
    for p in paragraphs:
        p = re.sub(r"\s*\n\s*", " ", p.strip())
        p = re.sub(r"[ \t ]+", " ", p)
        if p:
            out.append(p)
    return "\n\n".join(out)


def _sentence_spans(text: str, start: int, end: int) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    s = start
    for m in _BOUNDARY.finditer(text, start, end):
        punct = m.group(1)
        after = m.end()
        before = text[s:m.start(1)]
        tok_match = re.search(r"(\S+)$", before)
        token = tok_match.group(1).lower().lstrip("(\"'“‘[") if tok_match else ""
        if "." in punct and (token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha())):
            continue
        if after < end and text[after].islower():
            continue
        spans.append((s, m.end(1)))
        s = after
    if s < end:
        spans.append((s, end))
    return spans


def _split_long(text: str, a: int, b: int, max_len: int) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    while b - a > max_len:
        window = text[a:a + max_len]
        cut = max(window.rfind(", "), window.rfind("; "), window.rfind(": "))
        if cut < max_len // 3:
            cut = window.rfind(" ")
        cut = max_len if cut <= 0 else cut + 1
        out.append((a, a + cut))
        a += cut
        while a < b and text[a] == " ":
            a += 1
    if a < b:
        out.append((a, b))
    return out


def split_sentences(text: str, max_len: int = 400, min_len: int = 25) -> List[Chunk]:
    """Cut text into sentence-sized chunks with offsets into ``text``.

    Each line is treated as a paragraph boundary (run ``normalize`` first for
    PDF text). Very short sentences are merged with the next one; very long
    ones are split at a comma or space so the voice gets natural pauses and
    pause/skip stays responsive.
    """
    chunks: List[Chunk] = []
    for para in re.finditer(r"[^\n]+", text):
        if not para.group().strip():
            continue
        spans = _sentence_spans(text, para.start(), para.end())
        merged: List[Tuple[int, int]] = []
        for a, b in spans:
            if merged and (merged[-1][1] - merged[-1][0]) < min_len:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        for a, b in merged:
            for c, d in _split_long(text, a, b, max_len):
                piece = text[c:d]
                if piece.strip():
                    chunks.append(Chunk(piece, c, d))
    return chunks


def chunk_at(chunks: List[Chunk], offset: int) -> int:
    """Index of the chunk containing ``offset`` (or the next one). Past the end -> 0."""
    for i, c in enumerate(chunks):
        if offset < c.end:
            return i
    return 0
