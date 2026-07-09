"""Turn an uploaded file (PDF or image) into page images for VLM extraction.

The file ingestion path rasterises every page so the vision model can read
scanned/figure-heavy documents too — unlike a text-only PDF parser, which would
silently drop image-only pages.
"""

from typing import List, Tuple

import pymupdf

# (label, image_bytes, mime_type) for one renderable page/image.
PageImage = Tuple[str, bytes, str]

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
PDF_TYPES = {"application/pdf", "application/x-pdf"}

# Render PDF pages at 2x (~144 DPI): enough for the VLM to read body text without
# ballooning the base64 image payload sent on every request.
_PDF_ZOOM = 2.0


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
    ``ValueError`` for an unsupported type or an empty/corrupt file.
    """
    content_type = (content_type or "").split(";")[0].strip().lower()
    filename = filename or "upload"

    if not content:
        raise ValueError("Uploaded file is empty")

    if is_pdf(content_type, filename):
        return _pdf_to_images(content, filename)

    if is_image(content_type, filename):
        mime = content_type if content_type in SUPPORTED_IMAGE_TYPES else "image/png"
        return [(filename, content, mime)]

    raise ValueError(
        f"Unsupported file type '{content_type or filename}'. "
        "Upload a PDF or an image (png, jpg, webp, gif)."
    )


def _pdf_to_images(content: bytes, filename: str) -> List[PageImage]:
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:  # corrupt / not actually a PDF
        raise ValueError(f"Could not open PDF: {exc}") from exc

    pages: List[PageImage] = []
    try:
        matrix = pymupdf.Matrix(_PDF_ZOOM, _PDF_ZOOM)
        for i, page in enumerate(doc.pages()):
            pix = page.get_pixmap(matrix=matrix)
            pages.append((f"{filename} p.{i + 1}", pix.tobytes("png"), "image/png"))
    finally:
        doc.close()

    if not pages:
        raise ValueError("PDF has no pages")
    return pages
