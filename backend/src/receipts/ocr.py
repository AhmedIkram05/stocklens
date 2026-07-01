"""
Image preprocessing and OCR text extraction for receipt scanning.

Provides two core functions:
- ``preprocess_image`` — converts raw image bytes to a clean, deskewed grayscale array.
- ``extract_text`` — runs Tesseract OCR (LSTM engine) on the preprocessed image.
"""

import decimal
import re
from datetime import date
from decimal import Decimal

import cv2
import numpy as np
import pytesseract
import structlog

from src.config import settings

logger = structlog.get_logger()


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    """Preprocess a receipt image for optimal OCR accuracy.

    Steps
    -----
    1. Decode the raw bytes into an OpenCV ``ndarray`` (BGR).
    2. Convert to grayscale.
    3. Apply Gaussian adaptive thresholding — handles the uneven
       lighting common on crumpled receipts.
    4. Denoise with fast non-local means denoising.
    5. Deskew via affine rotation when the skew angle exceeds 0.5°.

    Parameters
    ----------
    image_bytes:
        Raw image bytes (JPEG, PNG, or HEIC).

    Returns
    -------
    np.ndarray
        Grayscale, thresholded, deskewed image ready for Tesseract.

    Raises
    ------
    ValueError
        If the bytes cannot be decoded into an image.
    """
    # ── Step 1: Decode ──────────────────────────────────────────────────────
    img_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image from bytes — unsupported format or corrupt data")

    logger.debug("image_decoded", shape=image.shape, dtype=image.dtype)

    # ── Step 2: Grayscale ───────────────────────────────────────────────────
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # ── Step 3: Denoise (before thresholding to reduce noise amplification) ─
    denoised = cv2.fastNlMeansDenoising(gray, h=10)

    # ── Step 4: Adaptive thresholding ───────────────────────────────────────
    # Gaussian method is more robust than simple global threshold for
    # receipts, which often have shadows, folds, and variable lighting.
    thresholded = cv2.adaptiveThreshold(
        denoised,
        maxValue=255,
        adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresholdType=cv2.THRESH_BINARY,
        blockSize=31,
        C=2,
    )

    # ── Step 5: Deskew ──────────────────────────────────────────────────────
    deskewed = _deskew(thresholded)

    return deskewed


def _deskew(image: np.ndarray) -> np.ndarray:
    """Rotate the image to correct a tilted scan.

    Finds the minimum-area rotated rectangle of all foreground pixels
    and computes the skew angle from it.  Images with an angle below
    0.5° are returned unchanged.

    Parameters
    ----------
    image:
        Binary (or grayscale) image to deskew.

    Returns
    -------
    np.ndarray
        Deskewed image (same dimensions as input).
    """
    coords = np.column_stack(np.where(image > 0))
    if len(coords) < 5:
        # Not enough foreground pixels to calculate a reliable angle.
        return image

    angle = cv2.minAreaRect(coords)[-1]

    # Normalise the angle to a small rotation.
    if angle < -45:
        angle = 90 + angle
    else:
        angle = -angle

    if abs(angle) < 0.5:
        return image  # Already straight enough.

    logger.debug("deskewing_image", angle_degrees=round(angle, 2))

    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, scale=1.0)

    return cv2.warpAffine(
        image,
        rotation_matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def extract_text(
    image: np.ndarray,
    tesseract_cmd: str | None = None,
) -> str:
    """Extract text from a preprocessed receipt image via Tesseract OCR.

    Uses the LSTM neural-net engine (``--oem 3``) and assumes the image
    contains a single uniform block of text (``--psm 6``).

    Parameters
    ----------
    image:
        Preprocessed grayscale (or binary) image.
    tesseract_cmd:
        Explicit path to the ``tesseract`` binary.  Falls back to
        ``settings.OCR_TESSERACT_CMD`` and then to the system default.

    Returns
    -------
    str
        Extracted text, stripped of leading/trailing whitespace.
    """
    # ── Configure tesseract binary path ─────────────────────────────────────
    cmd = tesseract_cmd or settings.OCR_TESSERACT_CMD
    if cmd:
        pytesseract.tesseract_cmd = cmd

    # ── Run OCR ─────────────────────────────────────────────────────────────
    config = "--oem 3 --psm 6"
    text: str = pytesseract.image_to_string(image, config=config)

    cleaned = text.strip()
    logger.debug(
        "ocr_extracted",
        char_count=len(cleaned),
        line_count=cleaned.count("\n") + 1 if cleaned else 0,
    )
    return cleaned


# ── Regex Parsing ─────────────────────────────────────────────────────────────


TOTAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:grand\s+)?total\s*[:.]?\s*[£$€]?\s*([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"amount\s+due\s*[:.]?\s*[£$€]?\s*([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"(?:total|due|balance)\s*[£$€]\s*([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"[£$€]\s*([\d,]+\.\d{2})\s*$", re.MULTILINE),
]

DATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b"),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b"),
    re.compile(
        r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May"
        r"|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?"
        r"|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
        r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?"
        r"|Dec(?:ember)?)\s+(\d{1,2}),?\s+(\d{4})\b",
        re.IGNORECASE,
    ),
]

PRICE_PATTERN: re.Pattern = re.compile(r"(\d+\.\d{2})\s*$")

MONTH_NAMES: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_total(text: str) -> Decimal | None:
    for pattern in TOTAL_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            amount_str = matches[-1].replace(",", "")
            try:
                return Decimal(amount_str)
            except ValueError, decimal.InvalidOperation:
                continue
    return None


def parse_merchant(text: str) -> str | None:
    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    for line in raw_lines:
        if re.search(r"\d", line):
            continue
        if re.match(
            r"^(receipt|invoice|thank|welcome|store|vat|tax|subtotal|sub\s*total"
            r"|total|amount|due|balance|change|payment|card|credit|debit|cash)",
            line,
            re.IGNORECASE,
        ):
            continue
        if len(line) < 3:
            continue
        if re.match(r"^\d{1,2}[/-]\d{1,2}", line):
            continue
        return line

    return None


def parse_line_items(text: str) -> list[dict]:
    items: list[dict] = []
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    total_amount = parse_total(text)

    for line in lines:
        price_match = PRICE_PATTERN.search(line)
        if not price_match:
            continue

        price = Decimal(price_match.group(1))

        if total_amount is not None and price >= total_amount:
            continue
        if re.search(r"(total|amount\s*due|balance|change|vat|tax\s*$)", line, re.IGNORECASE):
            continue

        desc = line[: price_match.start()].strip()
        if not desc:
            continue

        quantity = 1
        qty_match = re.search(r"(?:x\s*)?(\d+)(?:\s*x)?$", desc)
        if qty_match:
            quantity = int(qty_match.group(1))
            desc = desc[: qty_match.start()].strip()

        items.append(
            {
                "description": desc,
                "quantity": quantity,
                "amount": price,
            }
        )

    return items


def _normalise_day_month(day: int, month: int) -> tuple[int, int]:
    """Swap day/month when month > 12 to handle DD/MM vs MM/DD ambiguity.

    Preferred interpretation is DD/MM (UK locale). When the month value
    exceeds 12, the values must be swapped (MM/DD → DD/MM).
    """
    if month > 12:
        return month, day
    return day, month


def parse_date(text: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        groups = match.groups()
        try:
            if pattern == DATE_PATTERNS[0]:
                day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                day, month = _normalise_day_month(day, month)
                return date(year, month, day)
            if pattern == DATE_PATTERNS[1]:
                return date(int(groups[0]), int(groups[1]), int(groups[2]))
            if pattern == DATE_PATTERNS[2]:
                day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                day, month = _normalise_day_month(day, month)
                return date(year, month, day)
            if pattern == DATE_PATTERNS[3]:
                day, month_str, year = int(groups[0]), groups[1].lower()[:3], int(groups[2])
                return date(year, MONTH_NAMES[month_str], day)
            if pattern == DATE_PATTERNS[4]:
                month_str, day, year = groups[0].lower()[:3], int(groups[1]), int(groups[2])
                return date(year, MONTH_NAMES[month_str], day)
        except ValueError, KeyError:
            continue

    return None


def _compute_ocr_confidence(image: np.ndarray) -> float:
    data = pytesseract.image_to_data(
        image,
        config="--oem 3 --psm 6",
        output_type=pytesseract.Output.DICT,
    )
    confs = [c for i, c in enumerate(data["conf"]) if c > 0 and data["text"][i].strip()]
    return round(sum(confs) / len(confs) / 100.0, 4) if confs else 0.0


def process_receipt(image_bytes: bytes) -> dict:
    processed = preprocess_image(image_bytes)
    raw_text = extract_text(processed)

    if not raw_text.strip():
        return {
            "total_amount": None,
            "merchant_name": None,
            "line_items": [],
            "date": None,
            "ocr_confidence": 0.0,
            "ocr_raw_text": "",
        }

    total = parse_total(raw_text)
    merchant = parse_merchant(raw_text)
    items = parse_line_items(raw_text)
    parsed_date = parse_date(raw_text)
    confidence = _compute_ocr_confidence(processed)

    return {
        "total_amount": total,
        "merchant_name": merchant,
        "line_items": items,
        "date": parsed_date,
        "ocr_confidence": confidence,
        "ocr_raw_text": raw_text,
    }
