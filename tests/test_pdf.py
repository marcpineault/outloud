import pymupdf

from outloud.pdf import PdfDocument


def _make_pdf(path, text=None):
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(path)
    doc.close()


def test_text_page(tmp_path):
    p = tmp_path / "a.pdf"
    _make_pdf(p, "Hello world. This is a small test document for OutLoud.")
    doc = PdfDocument(str(p))
    assert doc.page_count == 1
    assert "small test document" in doc.page_text(0)
    assert doc.looks_scanned(0) is False
    doc.close()


def test_blank_page_looks_scanned_and_renders(tmp_path):
    p = tmp_path / "b.pdf"
    _make_pdf(p)
    doc = PdfDocument(str(p))
    assert doc.looks_scanned(0) is True
    img = doc.render(0, zoom=1.0)
    assert img.size[0] > 500 and img.size[1] > 700
    doc.close()
