import fitz  # PyMuPDF
from PIL import Image


def pdf_to_images(pdf_path: str) -> list[Image.Image]:
    """
    Convert PDF pages to PIL Image objects

    Args:
        pdf_path: Path to the PDF file

    Returns:
        List of PIL Image objects, one per page
    """
    doc = fitz.open(pdf_path)
    images = []

    for page in doc:
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)

    doc.close()
    return images