"""Tests for the file → page-image ingestion helper."""

import asyncio
import struct
import threading
import time

import pytest
import pymupdf

from server.core.config import config
from server.services import files
from server.services.files import file_to_page_images, render_page_images


def _make_pdf(pages: int = 1, text: str = "Hello world") -> bytes:
    """Build a tiny in-memory PDF with `pages` text pages."""
    doc = pymupdf.open()
    try:
        for _ in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), text)
        return doc.tobytes()
    finally:
        doc.close()


def test_pdf_renders_one_png_per_page():
    images = file_to_page_images(_make_pdf(pages=2), "application/pdf", "doc.pdf")
    assert len(images) == 2
    for label, data, mime in images:
        assert mime == "image/png"
        assert data.startswith(b"\x89PNG")  # PNG signature
        assert "doc.pdf" in label


def test_pdf_detected_by_extension_without_content_type():
    images = file_to_page_images(_make_pdf(), "", "report.PDF")
    assert len(images) == 1


def test_image_passes_through_unchanged():
    blob = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    images = file_to_page_images(blob, "image/png", "pic.png")
    assert images == [("pic.png", blob, "image/png")]


def test_image_by_extension_defaults_mime_to_png():
    # Unknown content-type but a recognised image extension still ingests.
    images = file_to_page_images(b"bytes", "application/octet-stream", "photo.jpg")
    assert len(images) == 1
    assert images[0][2] == "image/png"


def test_empty_file_raises():
    with pytest.raises(ValueError, match="empty"):
        file_to_page_images(b"", "application/pdf", "x.pdf")


def test_unsupported_type_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        file_to_page_images(b"some text", "text/plain", "notes.txt")


def test_corrupt_pdf_raises_value_error():
    with pytest.raises(ValueError):
        file_to_page_images(b"this is not a pdf", "application/pdf", "broken.pdf")


def _png_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a PNG's IHDR chunk."""
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_file_over_the_size_limit_is_refused(monkeypatch):
    monkeypatch.setattr(config, "max_upload_bytes", 10)
    with pytest.raises(ValueError, match="larger than"):
        file_to_page_images(b"x" * 11, "image/png", "big.png")


def test_pdf_over_the_page_limit_is_refused(monkeypatch):
    monkeypatch.setattr(config, "max_upload_pages", 2)
    with pytest.raises(ValueError, match="3 pages"):
        file_to_page_images(_make_pdf(pages=3), "application/pdf", "long.pdf")


def _pdf_with_page(width: float, height: float) -> bytes:
    """A one-page PDF of ``width`` x ``height`` points."""
    doc = pymupdf.open()
    try:
        doc.new_page(width=width, height=height)
        return doc.tobytes()
    finally:
        doc.close()


def test_giant_page_is_rendered_within_the_pixel_budget(monkeypatch):
    # 200 x 200 inches, the largest page PDF allows: ~830 Mpx (2.5 GB) at the
    # default 2x zoom.
    monkeypatch.setattr(config, "max_page_pixels", 1_000_000)
    pdf = _pdf_with_page(14_400, 14_400)

    [(_, data, _)] = file_to_page_images(pdf, "application/pdf", "huge.pdf")

    width, height = _png_size(data)
    assert width * height <= 1_000_000 * 1.01  # rounding to whole pixels


@pytest.mark.parametrize(
    "size", [(595, 842), (612, 792), (842, 1191)], ids=["A4", "Letter", "A3"]
)
def test_common_page_sizes_keep_the_full_zoom(size):
    [(_, data, _)] = file_to_page_images(
        _pdf_with_page(*size), "application/pdf", "doc.pdf"
    )
    assert _png_size(data) == (size[0] * 2, size[1] * 2)


def test_a_page_beyond_a3_is_scaled_down_by_default():
    # Every rendered page is held until the upload is transcribed, and vision
    # APIs scale large images down anyway: by default no page exceeds ~4 Mpx.
    pdf = _pdf_with_page(2000, 2000)  # 16 Mpx at the 2x zoom

    [(_, data, _)] = file_to_page_images(pdf, "application/pdf", "poster.pdf")

    width, height = _png_size(data)
    assert width * height <= 4_200_000 * 1.01


async def test_documents_are_rendered_one_at_a_time_on_one_thread(monkeypatch):
    # PyMuPDF must never run on two threads at once: concurrent uploads queue
    # up on a single rendering thread, which is not the event loop's.
    running, overlaps, threads = [], [], set()

    def render(content, filename):
        overlaps.append(len(running))
        running.append(filename)
        threads.add(threading.current_thread())
        time.sleep(0.02)
        running.remove(filename)
        return [(filename, b"png", "image/png")]

    monkeypatch.setattr(files, "_pdf_to_images", render)

    pages = await asyncio.gather(
        *(render_page_images(b"%PDF", "application/pdf", f"{i}.pdf") for i in range(4))
    )

    assert [label for [(label, _, _)] in pages] == ["0.pdf", "1.pdf", "2.pdf", "3.pdf"]
    assert overlaps == [0, 0, 0, 0]
    assert len(threads) == 1 and threading.main_thread() not in threads


def test_password_protected_pdf_is_refused():
    doc = pymupdf.open()
    try:
        doc.new_page()
        pdf = doc.tobytes(
            encryption=pymupdf.mupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )
    finally:
        doc.close()
    with pytest.raises(ValueError, match="Password-protected"):
        file_to_page_images(pdf, "application/pdf", "locked.pdf")
