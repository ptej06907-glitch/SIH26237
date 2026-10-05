"""Deterministic digital watermark challenge set; outputs measured JSON.

This is a small local regression corpus, not a statistical robustness certification.
"""

from __future__ import annotations

import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import pymupdf
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
from provenance.watermark import Candidate, detect_pdf, mark_pdf, render_locked_pdf, rerender_pdf  # noqa: E402

SECRET = b"sourcex-deterministic-benchmark-secret-v1"


def make_pdf(style: str) -> bytes:
    pdf = pymupdf.open()
    for page_number in range(2 if style == "two-page" else 1):
        page = pdf.new_page(width=595, height=842)
        page.insert_text((46, 65), f"SOURCEX SYNTHETIC {style.upper()} {page_number + 1}", fontsize=17)
        lines = 3 if style == "sparse" else 22
        for index in range(lines):
            page.insert_text((46, 110 + index * 29),
                             f"Fictional line {index:02d}: document {style}, page {page_number + 1}.", fontsize=10)
        if style == "dense":
            for index in range(12):
                page.draw_rect(pymupdf.Rect(320, 115 + 42 * index, 525, 140 + 42 * index),
                               color=(0.2, 0.4, 0.5), width=0.5)
    result = pdf.tobytes()
    pdf.close()
    return result


def raster_transform(pdf_bytes: bytes, *, shift: int = 0, rotation: float = 0) -> bytes:
    source = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    output = pymupdf.open()
    for page in source:
        pix = page.get_pixmap(dpi=140, colorspace=pymupdf.csRGB, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if shift:
            shifted = Image.new("RGB", image.size, "white")
            shifted.paste(image, (shift, shift))
            image = shifted
        if rotation:
            image = image.rotate(rotation, resample=Image.Resampling.BICUBIC, fillcolor="white")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        new_page = output.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=buffer.getvalue())
    result = output.tobytes(garbage=4, deflate=True)
    source.close()
    output.close()
    return result


def text_only_copy(pdf_bytes: bytes) -> bytes:
    source = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    output = pymupdf.open()
    for page in source:
        new_page = output.new_page(width=page.rect.width, height=page.rect.height)
        lines = page.get_text().splitlines()
        for index, line in enumerate(lines[:45]):
            new_page.insert_text((40, 50 + 17 * index), line[:110], fontsize=9)
    result = output.tobytes()
    source.close()
    output.close()
    return result


def run() -> dict:
    results = []
    for style in ("sparse", "dense", "two-page"):
        original = make_pdf(style)
        reference = render_locked_pdf(original)
        candidates = [Candidate(f"{style}-session-{i}", f"doc-{style}", f"nonce-{i}") for i in range(3)]
        marked, _ = mark_pdf(reference, candidates[1], SECRET)
        positives = {
            "exact": marked,
            "rerender": rerender_pdf(marked),
            "jpeg65": rerender_pdf(marked, 65),
            "scale90": rerender_pdf(marked, scale=0.9),
            "shift2px": raster_transform(marked, shift=2),
            "rotate1deg": raster_transform(marked, rotation=1),
        }
        negatives = {"original": original, "text-only reconstruction": text_only_copy(original)}
        for transformation, suspect in {**positives, **negatives}.items():
            detected = detect_pdf(suspect, reference, candidates, SECRET)
            expected = "INCONCLUSIVE" if transformation in negatives else "VALID"
            results.append({"document": style, "transformation": transformation,
                            "expected": expected, "status": detected["status"],
                            "matched_session_id": detected.get("matched_session_id"),
                            "correlation": detected.get("confidence"),
                            "correct": detected["status"] == expected and (
                                expected == "INCONCLUSIVE" or detected.get("matched_session_id") == candidates[1].session_id)})
    counts = defaultdict(lambda: {"passed": 0, "total": 0})
    for row in results:
        counts[row["transformation"]]["total"] += 1
        counts[row["transformation"]]["passed"] += int(row["correct"])
    return {"scope": "3 synthetic PDFs x 3 issued-session candidates; digital transforms only",
            "by_transformation": dict(counts), "cases": results,
            "false_attributions": sum(row["expected"] == "INCONCLUSIVE" and row["status"] == "VALID"
                                      for row in results)}


if __name__ == "__main__":
    report = run()
    path = ROOT / "artifacts" / "watermark-benchmark.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"by_transformation": report["by_transformation"],
                      "false_attributions": report["false_attributions"],
                      "output": str(path)}, indent=2))
    if any(not case["correct"] for case in report["cases"]):
        raise SystemExit(1)
