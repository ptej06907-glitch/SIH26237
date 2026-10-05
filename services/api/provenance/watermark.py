from __future__ import annotations

import hashlib
import hmac
import io
from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw

from .crypto import canonical, sha3

DPI = 140
GRID_COLUMNS = 24
GRID_ROWS = 32
DOT_RADIUS = 1
DOT_ALPHA = 8
CARRIER_VERSION = "visual-grid-v1"
CONTENT_MODE = "RENDER_LOCKED_V1"


@dataclass(frozen=True)
class Candidate:
    session_id: str
    document_id: str
    nonce: str


def _bits(secret: bytes, candidate: Candidate, page_index: int) -> np.ndarray:
    message = canonical({"carrier_version": CARRIER_VERSION, "session_id": candidate.session_id,
                         "document_id": candidate.document_id, "nonce": candidate.nonce,
                         "page_index": page_index})
    seed = int.from_bytes(hmac.new(secret, message, hashlib.sha3_256).digest()[:16], "big")
    return np.random.default_rng(seed).integers(0, 2, size=(GRID_ROWS, GRID_COLUMNS), dtype=np.uint8)


def _positions(width: int, height: int) -> Iterable[tuple[int, int, int, int]]:
    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):
            x = round((column + 0.5) * width / GRID_COLUMNS)
            y = round((row + 0.5) * height / GRID_ROWS)
            yield row, column, x, y


def _render(page: pymupdf.Page) -> np.ndarray:
    pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def _overlay_png(width: int, height: int, bits: np.ndarray) -> bytes:
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")
    for row, column, x, y in _positions(width, height):
        if bits[row, column]:
            draw.ellipse((x - DOT_RADIUS, y - DOT_RADIUS, x + DOT_RADIUS, y + DOT_RADIUS),
                         fill=(0, 0, 0, DOT_ALPHA))
    output = io.BytesIO()
    layer.save(output, format="PNG", optimize=True)
    return output.getvalue()


def mark_pdf(pdf_bytes: bytes, candidate: Candidate, secret: bytes) -> tuple[bytes, str]:
    source = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if source.page_count < 1 or source.page_count > 12:
        raise ValueError("PDF must have 1 to 12 pages")
    before_text = [page.get_text() for page in source]
    for index, page in enumerate(source):
        raster = _render(page)
        overlay = _overlay_png(raster.shape[1], raster.shape[0], _bits(secret, candidate, index))
        page.insert_image(page.rect, stream=overlay, keep_proportion=False, overlay=True)
    marked = source.tobytes(garbage=4, deflate=True)
    source.close()
    check = pymupdf.open(stream=marked, filetype="pdf")
    if [page.get_text() for page in check] != before_text:
        check.close()
        raise RuntimeError("Watermark operation altered selectable PDF text")
    check.close()
    commitment = sha3(canonical({"carrier_version": CARRIER_VERSION, "session_id": candidate.session_id,
                                 "document_id": candidate.document_id, "nonce": candidate.nonce}))
    return marked, commitment


def render_locked_pdf(pdf_bytes: bytes) -> bytes:
    """Make the issued PDF image-only before marking, removing easy text copy.

    This does not prevent OCR, screenshots, photographing, or manual transcription.
    """
    source = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    output = pymupdf.open()
    for page in source:
        pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csRGB, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=92, subsampling=0)
        target = output.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=buffer.getvalue())
    result = output.tobytes(garbage=4, deflate=True)
    source.close()
    output.close()
    return result


def text_reconstruction_pdf(pdf_bytes: bytes) -> bytes:
    """Negative control: recreating visible text does not retain a visual carrier."""
    source = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    output = pymupdf.open()
    for page in source:
        target = output.new_page(width=page.rect.width, height=page.rect.height)
        for index, line in enumerate(page.get_text().splitlines()[:45]):
            target.insert_text((40, 50 + 17 * index), line[:110], fontsize=9)
    result = output.tobytes()
    source.close()
    output.close()
    return result


def _aligned_suspect(base: np.ndarray, suspect: np.ndarray) -> np.ndarray:
    """Estimate small digital shifts/rotations from document features, not the carrier."""
    height, width = base.shape
    factor = min(1.0, 480 / max(width, height))
    small_size = (round(width * factor), round(height * factor))
    template = cv2.resize(base, small_size, interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    moving = cv2.resize(suspect, small_size, interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(template, moving, warp, cv2.MOTION_EUCLIDEAN,
                                       (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 60, 1e-5),
                                       None, 3)
    except cv2.error:
        return suspect
    if abs(float(warp[0, 1])) > 0.05 or max(abs(float(warp[0, 2])), abs(float(warp[1, 2]))) > 12:
        return suspect
    warp[0, 2] /= factor
    warp[1, 2] /= factor
    return cv2.warpAffine(suspect, warp, (width, height),
                          flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def _observations(base: np.ndarray, suspect: np.ndarray, align: bool = False) -> np.ndarray:
    if suspect.shape != base.shape:
        suspect = cv2.resize(suspect, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)
    if align:
        suspect = _aligned_suspect(base, suspect)
    residual = base.astype(np.float32) - suspect.astype(np.float32)
    values = np.empty((GRID_ROWS, GRID_COLUMNS), dtype=np.float32)
    for row, column, x, y in _positions(base.shape[1], base.shape[0]):
        patch = residual[max(0, y - DOT_RADIUS):y + DOT_RADIUS + 1,
                         max(0, x - DOT_RADIUS):x + DOT_RADIUS + 1]
        values[row, column] = float(np.mean(patch))
    return values


def detect_pdf(suspect_pdf: bytes, original_pdf: bytes, candidates: list[Candidate],
               secret: bytes) -> dict:
    """Reference-assisted visual detector. A hash or PDF metadata is never used here."""
    if not candidates:
        return {"status": "INCONCLUSIVE", "reason": "No issued sessions", "scores": []}
    try:
        suspect = pymupdf.open(stream=suspect_pdf, filetype="pdf")
        original = pymupdf.open(stream=original_pdf, filetype="pdf")
        if suspect.page_count != original.page_count:
            return {"status": "INCONCLUSIVE", "reason": "Page count differs", "scores": []}
        rendered = [(_render(original[index]), _render(suspect[index]))
                    for index in range(original.page_count)]
        observed = [_observations(base, found) for base, found in rendered]
        original.close()
        suspect.close()
    except Exception as exc:
        return {"status": "INCONCLUSIVE", "reason": f"PDF could not be rendered: {exc}", "scores": []}

    def rank(pages: list[np.ndarray]) -> list[dict]:
        ranked = []
        samples = np.concatenate([page.ravel() for page in pages])
        centered_samples = samples - float(np.mean(samples))
        for candidate in candidates:
            patterns = np.concatenate([_bits(secret, candidate, page).ravel()
                                       for page in range(len(pages))]).astype(np.float32)
            centered_pattern = patterns - float(np.mean(patterns))
            denominator = float(np.linalg.norm(centered_pattern) * np.linalg.norm(centered_samples))
            correlation = float(np.dot(centered_pattern, centered_samples) / denominator) if denominator > 0 else 0.0
            signal = float(np.mean(samples[patterns == 1]) - np.mean(samples[patterns == 0]))
            ranked.append({"session_id": candidate.session_id, "correlation": round(correlation, 4),
                           "signal": round(signal, 4)})
        return sorted(ranked, key=lambda item: item["correlation"], reverse=True)

    def winner(ranked: list[dict]) -> bool:
        first = ranked[0]
        second = ranked[1]["correlation"] if len(ranked) > 1 else 0.0
        return first["correlation"] >= 0.16 and first["signal"] >= 0.7 and first["correlation"] - second >= 0.08

    scores = rank(observed)
    if not winner(scores):
        aligned = [_observations(base, found, align=True) for base, found in rendered]
        aligned_scores = rank(aligned)
        if winner(aligned_scores):
            scores = aligned_scores
    first = scores[0]
    # Conservative starting thresholds. Tests must calibrate these against negatives.
    if not winner(scores):
        return {"status": "INCONCLUSIVE", "reason": "Carrier below threshold or ambiguous",
                "scores": scores, "matched_session_id": None}
    return {"status": "VALID", "reason": "Rendered-content carrier matched",
            "scores": scores, "matched_session_id": first["session_id"],
            "confidence": round(first["correlation"], 4)}


def rerender_pdf(pdf_bytes: bytes, jpeg_quality: int | None = None, scale: float = 1.0) -> bytes:
    """Create a flattened PDF for measured robustness checks."""
    source = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    result = pymupdf.open()
    for page in source:
        pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csRGB, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if scale != 1.0:
            image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        if jpeg_quality is None:
            image.save(buffer, format="PNG")
        else:
            image.save(buffer, format="JPEG", quality=jpeg_quality, subsampling=0)
        new_page = result.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=buffer.getvalue())
    output = result.tobytes(garbage=4, deflate=True)
    source.close()
    result.close()
    return output
