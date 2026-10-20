"""Generate PNG QR codes from HTTP or HTTPS URLs."""

from io import BytesIO
from urllib.parse import urlparse

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def generate_qr_code(link: str) -> bytes:
    """Return a QR code for ``link`` as PNG-encoded bytes."""
    link = link.strip()
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("link must be a valid HTTP or HTTPS URL")

    image = qrcode.QRCode(
        error_correction=ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    image.add_data(link)
    image.make(fit=True)

    output = BytesIO()
    image.make_image(fill_color="black", back_color="white").save(
        output,
        format="PNG",
    )
    return output.getvalue()
