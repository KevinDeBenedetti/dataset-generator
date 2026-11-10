"""Turn an uploaded file (PDF or image) into page images the LLM transcribes.

The file ingestion path rasterises every page so the LLM can read
scanned/figure-heavy documents too — unlike a text-only PDF parser, which would
silently drop image-only pages.
"""

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Optional, Tuple, TypeVar

import pymupdf

from server.core.config import config

# (label, image_bytes, mime_type) for one renderable page/image.
PageImage = Tuple[str, bytes, str]
T = TypeVar("T")

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
PDF_TYPES = {"application/pdf", "application/x-pdf"}

# Render PDF pages at 2x (~144 DPI): enough for the LLM to read body text without
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


class PageSource:
    """An upload opened for rendering, one page at a time.

    ``page_count`` pages; ``render(i)`` gives one as a :data:`PageImage`, so
    the caller can transcribe it and drop it before the next — a long PDF
    never has every page's bitmap in memory at once. A PDF stays open until
    ``close``. Every method runs on the rendering thread
    (:func:`on_render_thread`), the one PyMuPDF tolerates.
    """

    def __init__(
        self,
        filename: str,
        *,
        doc: Optional[pymupdf.Document] = None,
        image: Optional[PageImage] = None,
    ) -> None:
        self._filename = filename
        self._doc = doc
        self._image = image
        self.page_count = doc.page_count if doc is not None else 1

    def render(self, index: int) -> PageImage:
        if self._image is not None:
            return self._image
        if self._doc is None:
            raise RuntimeError("The upload is closed")
        page = self._doc[index]
        zoom = _zoom_for(page)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return (f"{self._filename} p.{index + 1}", pix.tobytes("png"), "image/png")

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None


def open_pages(content: bytes, content_type: str, filename: str) -> PageSource:
    """Validate an upload and open it for rendering (see :class:`PageSource`).

    PDFs are rasterised page by page; an image is its own single page. Raises
    ``ValueError`` for an unsupported type, an empty/corrupt file, or a PDF
    over ``config.max_upload_pages``. The byte limit is the route's
    (api/generate.py bounds its read to ``config.max_upload_bytes``).
    """
    content_type = (content_type or "").split(";")[0].strip().lower()
    filename = filename or "upload"

    if not content:
        raise ValueError("Uploaded file is empty")

    if is_pdf(content_type, filename):
        return PageSource(filename, doc=_open_pdf(content))

    if is_image(content_type, filename):
        mime = content_type if content_type in SUPPORTED_IMAGE_TYPES else "image/png"
        return PageSource(filename, image=(filename, content, mime))

    raise ValueError(
        f"Unsupported file type '{content_type or filename}'. "
        "Upload a PDF or an image (png, jpg, webp, gif)."
    )


def file_to_page_images(
    content: bytes, content_type: str, filename: str
) -> List[PageImage]:
    """Every page of an upload rendered at once — :func:`open_pages` for a
    caller that needs them all together."""
    source = open_pages(content, content_type, filename)
    try:
        return [source.render(i) for i in range(source.page_count)]
    finally:
        source.close()


async def on_render_thread(fn: Callable[..., T], *args: Any) -> T:
    """Run ``fn`` on the rendering thread: off the event loop, one call after
    the other."""
    return await asyncio.get_running_loop().run_in_executor(_RENDER_THREAD, fn, *args)


async def render_page_images(
    content: bytes, content_type: str, filename: str
) -> List[PageImage]:
    """:func:`file_to_page_images` on the rendering thread."""
    return await on_render_thread(file_to_page_images, content, content_type, filename)


def _zoom_for(page: pymupdf.Page) -> float:
    """The render zoom of ``page``: :data:`_PDF_ZOOM`, lowered when needed so
    the bitmap stays within ``config.max_page_pixels`` — a PDF can declare any
    page size, and rendering one 200-inch page at 2x would take gigabytes."""
    area = page.rect.width * page.rect.height  # pixels at zoom 1
    if area <= 0:
        return _PDF_ZOOM
    return min(_PDF_ZOOM, math.sqrt(config.max_page_pixels / area))


def _open_pdf(content: bytes) -> pymupdf.Document:
    """The PDF opened and checked: not encrypted, not empty, within the page cap."""
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:  # corrupt / not actually a PDF
        raise ValueError(f"Could not open PDF: {exc}") from exc
    try:
        if doc.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if doc.page_count > config.max_upload_pages:
            raise ValueError(
                f"The PDF has {doc.page_count} pages; at most "
                f"{config.max_upload_pages} can be processed"
            )
        if doc.page_count == 0:
            raise ValueError("PDF has no pages")
    except ValueError:
        doc.close()
        raise
    return doc
