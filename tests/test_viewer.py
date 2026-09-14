import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

import pymupdf  # after Qt: see conftest.py

from outloud.pdf import PdfDocument
from outloud.viewer import PdfViewer


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pdf(path, pages=5):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1} text. Another sentence here.", fontsize=14)
    doc.save(path)
    doc.close()


def test_layout_navigation_and_hit_testing(app, tmp_path):
    p = tmp_path / "v.pdf"
    _pdf(p)
    view = PdfViewer()
    view.resize(800, 600)
    view.show()
    app.processEvents()
    view.set_document(PdfDocument(str(p)))
    app.processEvents()
    assert view.page_count == 5
    assert view.offsets == sorted(view.offsets) and view.doc_h > 5 * 600
    assert abs(view.page_w - (view.viewport().width() - 2 * view.MARGIN)) < 1  # fit width

    pages = []
    view.currentPageChanged.connect(pages.append)
    view.goto_page(3)
    app.processEvents()
    assert view.current_page == 3 and pages[-1] == 3

    hits = []
    view.clicked.connect(lambda i, x, y: hits.append((i, x, y)))
    # the top-left of page 3 sits at (page_x, offset - scroll); click 50pt into it
    s = view.scale[3]
    vx = view._page_x(3) + 50 * s
    vy = view.offsets[3] - view.verticalScrollBar().value() + 60 * s
    view.clicked.emit(*view.page_point_at(QPointF(vx, vy)))
    assert hits and hits[0][0] == 3 and abs(hits[0][1] - 50) < 1 and abs(hits[0][2] - 60) < 1

    view.set_highlight(3, [(72, 60, 300, 80)])
    view._render_pending()
    assert 3 in view.cache
    before = view.page_w
    view.zoom_in()
    assert view.page_w > before and not view.cache
    view.fit_width()
    assert abs(view.page_w - before) < 1
