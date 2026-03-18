import fitz  # PyMuPDF
from PIL import Image


def pdf_to_images(source: str | bytes) -> list[Image.Image]:
    """
    Convert PDF pages to PIL Image objects

    Args:
        source: File path (str) or raw bytes (bytes)

    Returns:
        List of PIL Image objects, one per page
    """
    if isinstance(source, bytes):
        doc = fitz.open(stream=source, filetype="pdf")
    else:
        doc = fitz.open(source)

    images = []
    for page in doc:
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)

    doc.close()
    return images


def file_to_images(source: str | bytes, filetype: str) -> list[Image.Image]:
    """
    Convert file to PIL Image objects based on file type

    Args:
        source: File path (str) or raw bytes (bytes)
        filetype: File extension (e.g. "pdf", "png", "jpg")

    Returns:
        List of PIL Image objects
    """
    filetype = filetype.lower().lstrip(".")

    if filetype == "pdf":
        return pdf_to_images(source)

    if filetype in ("png", "jpg", "jpeg", "bmp", "webp"):
        if isinstance(source, bytes):
            import io
            return [Image.open(io.BytesIO(source))]
        return [Image.open(source)]

    raise ValueError(f"Unsupported file type: {filetype}")