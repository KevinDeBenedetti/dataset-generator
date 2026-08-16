"""Tests for the file → page-image ingestion helper."""

import pytest
import pymupdf

from server.services.files import file_to_page_images


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
