import pymupdf

from outloud.pdf import PageText, PdfDocument, Token


def _make_pdf(path, text=None, image=False, rotate=0, size=(595, 842), at=(72, 72)):
    doc = pymupdf.open()
    page = doc.new_page(width=size[0], height=size[1])
    if text:
        page.insert_text(at, text, fontsize=12)
    if image:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), 0)
        pix.clear_with(200)
        page.insert_image(page.rect, pixmap=pix)
    if rotate:
        page.set_rotation(rotate)
    doc.save(path)
    doc.close()


def test_text_page_and_word_map(tmp_path):
    p = tmp_path / "a.pdf"
    _make_pdf(p, "Hello world. This is a small test document for OutLoud.")
    doc = PdfDocument(str(p))
    assert doc.page_count == 1
    assert "small test document" in doc.page_text(0)
    assert doc.looks_scanned(0) is False
    pt = doc.page_text_map(0)
    assert [c.text for c in pt.chunks] == ["Hello world. This is a small test document for OutLoud."] or len(pt.chunks) == 2
    rects = pt.rects_for_chunk(0)
    assert rects and all(0 <= r[0] < r[2] <= pt.width and 0 <= r[1] < r[3] <= pt.height for r in rects)
    # a click on the first word lands in the first chunk; a click far away lands nowhere
    x0, y0, x1, y1 = pt.tokens[0].rect
    assert pt.chunk_at_point((x0 + x1) / 2, (y0 + y1) / 2) == 0
    assert pt.chunk_at_point(300, 700) is None
    doc.close()


def test_blank_and_scanned_detection(tmp_path):
    blank = tmp_path / "blank.pdf"
    _make_pdf(blank)
    doc = PdfDocument(str(blank))
    assert doc.is_blank(0) and not doc.looks_scanned(0)
    doc.close()
    scan = tmp_path / "scan.pdf"
    _make_pdf(scan, image=True)
    doc = PdfDocument(str(scan))
    assert doc.looks_scanned(0) is True
    img = doc.render(0, zoom=1.0)
    assert img.size == (595, 842)
    w, h, stride, data = doc.render_rgb(0, 0.5)
    assert (w, h) == (298, 421) and len(data) == stride * h
    doc.close()


def test_rotated_page_boxes_land_inside_the_displayed_page(tmp_path):
    p = tmp_path / "rot.pdf"
    # word near the bottom of a tall narrow page (unrotated y ~ 550); once the page is shown
    # rotated 90 degrees it is 600 wide and 200 tall, so an untransformed box would spill out.
    _make_pdf(p, "Sideways", rotate=90, size=(200, 600), at=(20, 550))
    doc = PdfDocument(str(p))
    w, h = doc.page_size(0)
    assert (round(w), round(h)) == (600, 200)
    toks = doc.page_words(0)
    assert toks
    for tok in toks:
        x0, y0, x1, y1 = tok.rect
        assert 0 <= x0 <= x1 <= w and 0 <= y0 <= y1 <= h
    doc.close()


def test_hyphenated_line_break_is_glued():
    toks = [
        Token("An", (0, 0, 10, 10), 0, 0),
        Token("inter-", (12, 0, 40, 10), 0, 0),
        Token("national", (0, 12, 40, 22), 0, 1),
        Token("deal.", (42, 12, 60, 22), 0, 1),
        Token("Next", (0, 40, 30, 50), 1, 0),
    ]
    pt = PageText(toks, 100, 100)
    assert pt.text == "An international deal.\nNext"
    assert [c.text for c in pt.chunks] == ["An international deal.", "Next"]
    assert len(pt.rects_for_chunk(0)) == 2  # two printed lines


def test_ocr_lines_become_tokens():
    laid = [(0, 0, "First line", 0.1, 0.1, 0.9, 0.15), (0, 1, "second line.", 0.1, 0.16, 0.9, 0.21), (1, 2, "New paragraph.", 0.1, 0.4, 0.5, 0.45)]
    pt = PageText.from_ocr_lines(laid, 500, 1000)
    assert pt.text == "First line second line.\nNew paragraph."
    assert pt.chunk_at_point(250, 425) == 1


def test_block_per_line_pdf_keeps_sentences_whole(tmp_path):
    """insert_textbox writes one block per printed line; sentences must still span lines."""
    p = tmp_path / "lines.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Chapter 1", fontsize=22)
    body = ("OutLoud reads this page to you and follows along with a highlighter. Click any sentence "
            "and it starts reading from there. Type a page number at the top and press Enter to jump.\n\n"
            "Scanned pages are read too when a page has no text layer.")
    page.insert_textbox(pymupdf.Rect(72, 110, 400, 700), body, fontsize=12, lineheight=1.4)
    doc.save(p)
    doc.close()
    pt = PdfDocument(str(p)).page_text_map(0)
    texts = [c.text for c in pt.chunks]
    assert texts[0] == "Chapter 1"
    assert "Click any sentence and it starts reading from there." in texts
    i = texts.index("Click any sentence and it starts reading from there.")
    assert len(pt.rects_for_chunk(i)) >= 2  # the sentence wraps, so it highlights on 2+ lines
    assert pt.text.count("\n") == 2  # heading | paragraph | paragraph
