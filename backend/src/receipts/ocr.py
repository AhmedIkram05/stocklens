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

    # ── Step 3: Scale to a Tesseract-friendly size ─────────────────────────
    # Phone photos can be 12 MP+ (text too small) or tiny crops (too little
    # detail).  Normalise the long edge so characters land near ~300 DPI.
    h, w = gray.shape[:2]
    long_side = max(h, w)
    if long_side < 900:
        scale = 900.0 / long_side
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    elif long_side > 3000:
        scale = 3000.0 / long_side
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    # ── Step 4: Auto-invert so text is dark on a light background ──────────
    # Amateur photos often have a dark background; Tesseract assumes dark
    # text on light.  Flip when the mean luminance is low.
    if gray.mean() < 127:
        gray = cv2.bitwise_not(gray)

    # ── Step 5: Light blur + Otsu binarisation ─────────────────────────────
    # Gaussian blur is cheaper than non-local means and preserves strokes
    # while killing photographic noise.  Otsu picks a global threshold that
    # is robust to the uneven lighting common on crumpled receipts.
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresholded = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    # Reconnect strokes broken up by noisy scans.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    thresholded = cv2.morphologyEx(thresholded, cv2.MORPH_CLOSE, kernel)

    # Binarisation occasionally yields an all-white (no foreground) image
    # when the polarity is still wrong — flip once and retry.
    if np.count_nonzero(thresholded == 0) < 0.01 * thresholded.size:
        thresholded = cv2.bitwise_not(thresholded)

    # ── Step 6: Deskew ──────────────────────────────────────────────────────
    deskewed = _deskew(thresholded)

    return deskewed


def _deskew(image: np.ndarray) -> np.ndarray:
    """Rotate the image to correct a tilted scan.

    Finds the minimum-area rotated rectangle of all *text* pixels (dark on
    a light background) and computes the skew angle from it.  Images with an
    angle below 0.5° are returned unchanged.

    Parameters
    ----------
    image:
        Binary (or grayscale) image to deskew.

    Returns
    -------
    np.ndarray
        Deskewed image (same dimensions as input).
    """
    # Text pixels are dark (value < 128) after binarisation.
    coords = np.column_stack(np.where(image < 128))
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
    # Try several page-segmentation modes and keep the most text.  --psm 6
    # (uniform block) is the common case; --psm 4 (single column) and --psm 11
    # (sparse text) recover receipts where 6 yields almost nothing.
    best = ""
    for config in ("--oem 3 --psm 6", "--oem 3 --psm 4", "--oem 3 --psm 11"):
        try:
            text = pytesseract.image_to_string(image, config=config)
        except Exception:
            continue
        if len(text.strip()) > len(best.strip()):
            best = text
        if len(best.strip()) > 20:
            break

    cleaned = best.strip()
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

# Tolerant keyword matcher for the line that holds the total.  Allows OCR
# corruption of "total" (t0tal, t o t a l), and covers multilingual labels
# (Lidl/German receipts: SUMME, GESAMT, BETRA G, ZWISCHENSUMME).
_TOTAL_KEYWORD: re.Pattern = re.compile(
    r"(?:grand\s+)?t[\s]*[o0][\s]*t[\s]*[a0][\s]*l"
    r"|summe|gesamt|betrag|zwischensumme"
    r"|amount\s+(?:due|paid)|balance\s+due|to\s+pay"
    r"|sub[\s]*total",
    re.IGNORECASE,
)

# A monetary amount: digits with an optional decimal comma/point.  The dot
# or comma is required so bare integers (e.g. a clock time "17:34") are
# never mistaken for money.
_MONEY_TOKEN: re.Pattern = re.compile(r"\d[\d\s]*[.,]\s*\d{1,2}")

DATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b"),  # DD/MM/YYYY
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),  # YYYY-MM-DD
    re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b"),  # DD-MM-YYYY
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
    re.compile(r"\b(\d{1,2})[.](\d{1,2})[.](\d{2,4})\b"),  # DD.MM.YYYY
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"),  # DD/MM/YY
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


def _clean_number(raw: str) -> Decimal | None:
    """Parse a possibly-noisy numeric token into a ``Decimal``.

    Handles the artefacts Tesseract produces on receipts:
    - spaces inside numbers (``2 . 8 8`` → ``2.88``)
    - decimal commas (``2,88`` → ``2.88``; European ``1.234,56``)
    - thousands separators
    """
    s = raw.strip().replace(" ", "")
    if not s:
        return None

    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        # European style when the comma is the rightmost separator.
        s = s.replace(".", "") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif has_comma:
        parts = s.split(",")
        # Decimal comma only when not a 3-digit thousands group.
        s = s.replace(",", ".") if len(parts) == 2 and len(parts[1]) != 3 else s.replace(",", "")

    if not re.search(r"\d", s):
        return None
    try:
        return Decimal(s)
    except ValueError, decimal.InvalidOperation:
        return None


def parse_total(text: str) -> Decimal | None:
    # 1. Strict keyword patterns (original behaviour — fast path).
    for pattern in TOTAL_PATTERNS:
        matches = pattern.findall(text)
        for raw in reversed(matches):
            amount = _clean_number(raw)
            if amount is not None:
                return amount

    # 2. Fuzzy keyword scan — tolerate OCR corruption & multilingual labels.
    #    On the matching line, take the last monetary value.
    for line in text.splitlines():
        if not _TOTAL_KEYWORD.search(line):
            continue
        tokens = _MONEY_TOKEN.findall(line)
        for raw in reversed(tokens):
            amount = _clean_number(raw)
            if amount is not None:
                return amount

    # No recognizable total line → return None so the cascade can escalate to
    # the LLM or the caller can prompt for manual entry, rather than guessing
    # a wrong amount from a line item.
    return None


# Lines that look like store addresses / contact details rather than a name.
_MERCHANT_NOISE: re.Pattern = re.compile(
    r"(street|road|lane|avenue|ave|st\.|drive|dr\.|court|ct\.|close|way|"
    r"http|www|\.com|tel:|phone|fax|e-?mail|"
    r"\b\d{3,5}\s*\d{3,5}\b"  # phone-like number cluster
    r"|[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d?[A-Z]{2})",  # UK-style postcode
    re.IGNORECASE,
)


def parse_merchant(text: str) -> str | None:
    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # Only the top of the receipt is a candidate for the merchant name.
    candidates: list[str] = []
    for line in raw_lines[:8]:
        if len(line) < 3 or len(line) > 40:
            continue
        if re.search(r"\d", line):
            continue  # store numbers, dates, prices — not the name
        if _MERCHANT_NOISE.search(line):
            continue
        if re.match(
            r"^(receipt|invoice|thank|welcome|store|vat|tax|subtotal|sub\s*total"
            r"|total|amount|due|balance|change|payment|card|credit|debit|cash"
            r"|date|time)",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.match(r"^\d{1,2}[/-]\d{1,2}", line):
            continue
        candidates.append(line)

    # Prefer a candidate that fuzzy-matches a known merchant (raw text kept).
    try:
        from src.receipts.merchant_match import fuzzy_match_merchant

        known_candidates = [c for c in candidates if fuzzy_match_merchant(c)[1] >= 80]
        if known_candidates:
            return known_candidates[0]

        # Rescuer: the merchant may be embedded in a greeting line
        # ("WELCOME TO SAINSBURY S") that was filtered from candidates.
        for line in raw_lines[:5]:
            if fuzzy_match_merchant(line)[1] >= 80:
                return line
    except Exception:
        pass

    return candidates[0] if candidates else None


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
            if pattern == DATE_PATTERNS[5]:
                day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                if year < 100:
                    year += 2000
                day, month = _normalise_day_month(day, month)
                return date(year, month, day)
            if pattern == DATE_PATTERNS[6]:
                day, month, year = int(groups[0]), int(groups[1]), int(groups[2]) + 2000
                day, month = _normalise_day_month(day, month)
                return date(year, month, day)
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
