from outloud.textsplit import chunk_at, normalize, split_sentences


def test_normalize_joins_pdf_lines_and_dehyphenates():
    raw = "This is an inter-\nnational line\nthat wraps.\n\nNew paragraph\r\nhere."
    assert normalize(raw) == "This is an international line that wraps.\n\nNew paragraph here."


def test_split_basic_offsets_round_trip():
    text = "First sentence is here. Second one follows! Third asks a question? Fourth ends it."
    chunks = split_sentences(text, min_len=5)
    assert [c.text for c in chunks] == [
        "First sentence is here.",
        "Second one follows!",
        "Third asks a question?",
        "Fourth ends it.",
    ]
    for c in chunks:
        assert text[c.start:c.end] == c.text


def test_abbreviations_and_initials_do_not_split():
    text = "Dr. Smith met J. K. Rowling in the U.S. last year. They talked about Fig. 3 for hours."
    chunks = split_sentences(text, min_len=5)
    assert [c.text for c in chunks] == [
        "Dr. Smith met J. K. Rowling in the U.S. last year.",
        "They talked about Fig. 3 for hours.",
    ]


def test_lowercase_after_period_is_not_a_boundary():
    chunks = split_sentences("We bought apples, pears, etc. and went home. Then we slept.", min_len=5)
    assert len(chunks) == 2


def test_short_sentences_merge_and_long_ones_split():
    short = "Yes. No. Maybe so, and then a longer thought arrives at last."
    merged = split_sentences(short, min_len=25)
    assert merged[0].text.startswith("Yes. No.")
    long = "word " * 200
    pieces = split_sentences(long.strip(), max_len=100)
    assert len(pieces) >= 9
    assert all(len(p.text) <= 100 for p in pieces)
    assert "".join(p.text + " " for p in pieces).split() == long.split()


def test_paragraphs_are_separate_chunks_and_chunk_at():
    text = "Heading without punctuation\n\nBody sentence one. Body sentence two."
    chunks = split_sentences(text, min_len=5)
    assert chunks[0].text == "Heading without punctuation"
    assert chunk_at(chunks, 0) == 0
    assert chunk_at(chunks, chunks[1].start + 3) == 1
    assert chunk_at(chunks, len(text) + 5) == 0  # past the end restarts
