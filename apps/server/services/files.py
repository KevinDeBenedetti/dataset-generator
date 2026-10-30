"""Turn an uploaded file (PDF or image) into page images for VLM extraction.

The file ingestion path rasterises every page so the vision model can read
scanned/figure-heavy documents too — unlike a text-only PDF parser, which would
silently drop image-only pages.
"""

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

import pymupdf

from server.core.config import config

# (label, image_bytes, mime_type) for one renderable page/image.
PageImage = Tuple[str, bytes, str]

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
PDF_TYPES = {"application/pdf", "application/x-pdf"}

# Render PDF pages at 2x (~144 DPI): enough for the VLM to read body text without
# ballooning the base64 image payload sent on every request.
_PDF_ZOOM = 2.0

# PyMuPDF does not support running on several threads, which "may cause
# incorrect behaviour or even crash Python itself": uploads are rendered on
# this single thread, never on the default pool where they would overlap.
_RENDER_THREAD = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pymupdf")


def is_pdf(content_type: str, filename: str) -> bool:
    return content_type in PDF_TYPES or filename.lower().endswith(".pdf")


def is_image(content_type: str, filename: str) -> bool:
    return content_type in SUPPORTED_IMAGE_TYPES or filename.lower().endswith(
        IMAGE_EXTENSIONS
    )


def file_to_page_images(
    content: bytes, content_type: str, filename: str
) -> List[PageImage]:
    """Render an uploaded file to one image per page.

    PDFs are rasterised page-by-page; images pass through unchanged. Raises
    ``ValueError`` for an unsupported type, an empty/corrupt file, or a file
    over the upload limits (``config.max_upload_*``).
    """
    content_type = (content_type or "").split(";")[0].strip().lower()
    filename = filename or "upload"

    if not content:
        raise ValueError("Uploaded file is empty")
    if len(content) > config.max_upload_bytes:
        raise ValueError(
            f"The file is larger than {config.max_upload_bytes // (1024 * 1024)} MB"
        )

    if is_pdf(content_type, filename):
        return _pdf_to_images(content, filename)

    if is_image(content_type, filename):
        mime = content_type if content_type in SUPPORTED_IMAGE_TYPES else "image/png"
        return [(filename, content, mime)]

    raise ValueError(
        f"Unsupported file type '{content_type or filename}'. "
        "Upload a PDF or an image (png, jpg, webp, gif)."
    )


async def render_page_images(
    content: bytes, content_type: str, filename: str
) -> List[PageImage]:
    """:func:`file_to_page_images` on the rendering thread: off the event loop,
    one file after the other."""
    return await asyncio.get_running_loop().run_in_executor(
        _RENDER_THREAD, file_to_page_images, content, content_type, filename
    )


def _zoom_for(page: pymupdf.Page) -> float:
    """The render zoom of ``page``: :data:`_PDF_ZOOM`, lowered when needed so
    the bitmap stays within ``config.max_page_pixels`` — a PDF can declare any
    page size, and rendering one 200-inch page at 2x would take gigabytes."""
    area = page.rect.width * page.rect.height  # pixels at zoom 1
    if area <= 0:
        return _PDF_ZOOM
    return min(_PDF_ZOOM, math.sqrt(config.max_page_pixels / area))


def _pdf_to_images(content: bytes, filename: str) -> List[PageImage]:
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:  # corrupt / not actually a PDF
        raise ValueError(f"Could not open PDF: {exc}") from exc

    pages: List[PageImage] = []
    try:
        if doc.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if doc.page_count > config.max_upload_pages:
            raise ValueError(
                f"The PDF has {doc.page_count} pages; at most "
                f"{config.max_upload_pages} can be processed"
            )
        for i, page in enumerate(doc.pages()):
            zoom = _zoom_for(page)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            pages.append((f"{filename} p.{i + 1}", pix.tobytes("png"), "image/png"))
    finally:
        doc.close()

    if not pages:
        raise ValueError("PDF has no pages")
    return pages
