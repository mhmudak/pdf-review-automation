#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

SCHEMA_VERSION = "2.2"

FIELDS = [
    "schema_version",
    "source_file",
    "source_sha256",
    "reviewer",
    "raw_author",
    "pdf_page",
    "book_page",
    "mapping_method",
    "mapping_confidence",
    "annotation_type",
    "comment",
    "selected_text",
    "subject",
    "created",
    "modified",
    "annotation_id",
    "identity_key",
    "fallback_fingerprint",
    "xref",
    "reply_to_xref",
    "rect_x0",
    "rect_y0",
    "rect_x1",
    "rect_y1",
    "is_empty",
    "import_candidate",
    "skip_reason",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u200a", " ").replace("\u200f", " ").replace("\u200e", " ")
    return re.sub(r"\s+", " ", text).strip()


def page_fingerprint(page: fitz.Page) -> str:
    return hashlib.sha256(normalize_text(page.get_text("text")).encode("utf-8")).hexdigest()


def pdf_date(value: str) -> str:
    if not value:
        return ""
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})([Zz]|[+-]\d{2}'?\d{2}'?)?", value)
    if not m:
        return value
    y, mo, d, hh, mm, ss, tz = m.groups()
    out = f"{y}-{mo}-{d}T{hh}:{mm}:{ss}"
    if not tz:
        return out
    if tz.upper() == "Z":
        return out + "Z"
    tz = tz.replace("'", "")
    return out + tz[:3] + ":" + tz[3:]


def overlap(a: fitz.Rect, b: fitz.Rect) -> float:
    x0, y0 = max(a.x0, b.x0), max(a.y0, b.y0)
    x1, y1 = min(a.x1, b.x1), min(a.y1, b.y1)
    return max(0, x1 - x0) * max(0, y1 - y0)


def marked_text(page: fitz.Page, annot: fitz.Annot) -> str:
    vertices = annot.vertices or []
    if not vertices:
        return ""
    words = page.get_text("words")
    selected: list[str] = []
    try:
        for i in range(0, len(vertices), 4):
            quad_points = vertices[i : i + 4]
            if len(quad_points) < 4:
                continue
            quad_rect = fitz.Quad(quad_points).rect
            for word in words:
                word_rect = fitz.Rect(word[:4])
                inter = overlap(quad_rect, word_rect)
                if inter / max(1e-9, word_rect.get_area()) >= 0.20:
                    selected.append(word[4])
    except Exception:
        return ""
    return " ".join(selected).strip()


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"reviewer_aliases": {}, "empty_annotation_rules": {"default": "keep"}}
    return json.loads(path.read_text(encoding="utf-8"))


def build_master_index(master_pdf: Path) -> dict[str, dict[str, Any]]:
    doc = fitz.open(master_pdf)
    index: dict[str, dict[str, Any]] = {}
    for pno, page in enumerate(doc, start=1):
        label = page.get_label().strip() if hasattr(page, "get_label") else ""
        index[page_fingerprint(page)] = {
            "master_pdf_page": pno,
            "book_page": label or str(pno),
        }
    doc.close()
    return index


def load_master_index(path: Path) -> dict[str, dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def footer_page_candidates(page: fitz.Page) -> list[str]:
    """Extract standalone numeric page-number candidates from the bottom 20% of a text PDF."""
    candidates: list[str] = []
    cutoff = page.rect.height * 0.80
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return candidates
    for block in blocks:
        x0, y0, x1, y1, text = block[:5]
        if y1 < cutoff:
            continue
        normalized = normalize_text(str(text)).translate(ARABIC_DIGITS)
        for token in re.findall(r"(?<!\\d)\\d{1,4}(?!\\d)", normalized):
            if token not in candidates:
                candidates.append(token)
    return candidates


def _footer_check(book_page: str, candidates: list[str]) -> tuple[str, float]:
    if not book_page or not book_page.isdigit() or not candidates:
        return "", 0.0
    if str(int(book_page)) in {str(int(c)) for c in candidates if c.isdigit()}:
        return "footer_verified", 1.0
    return "footer_mismatch", 0.6


def infer_book_page(page: fitz.Page, pdf_page: int, master_index: dict[str, dict[str, Any]] | None) -> tuple[str, str, float, str, str]:
    footer_candidates = footer_page_candidates(page)
    footer_candidate = footer_candidates[0] if footer_candidates else ""

    if master_index:
        match = master_index.get(page_fingerprint(page))
        if match:
            book_page = str(match["book_page"])
            footer_status, confidence = _footer_check(book_page, footer_candidates)
            if footer_status == "footer_verified":
                return book_page, "master_text_fingerprint+footer_verified", 1.0, footer_candidate, footer_status
            if footer_status == "footer_mismatch":
                return book_page, "master_text_fingerprint+footer_mismatch", confidence, footer_candidate, footer_status
            return book_page, "master_text_fingerprint", 1.0, footer_candidate, ""

    try:
        label = page.get_label().strip()
    except Exception:
        label = ""
    if label:
        footer_status, confidence = _footer_check(label, footer_candidates)
        if footer_status == "footer_verified":
            return label, "pdf_page_label+footer_verified", 1.0, footer_candidate, footer_status
        if footer_status == "footer_mismatch":
            return label, "pdf_page_label+footer_mismatch", confidence, footer_candidate, footer_status
        return label, "pdf_page_label", 1.0, footer_candidate, ""

    # Footer numbers are evidence only, never silently accepted as the canonical book page.
    if footer_candidate:
        return "", "footer_only_unverified", 0.25, footer_candidate, "footer_only"
    return "", "unresolved", 0.0, "", ""

def _looks_like_full_name(value: str, generic_values: set[str]) -> bool:
    clean = normalize_text(value)
    if not clean or clean.lower() in generic_values:
        return False
    parts = [p for p in re.split(r"\s+", clean) if p]
    if len(parts) < 2:
        return False
    return all(any(ch.isalpha() for ch in part) for part in parts[:4])


def _filename_reviewer_candidate(filename: str, aliases: dict[str, str], generic_values: set[str]) -> str:
    stem = Path(filename).stem
    normalized = normalize_text(re.sub(r"[_.()\\-]+", " ", stem))
    lowered = normalized.lower()

    # Known aliases may be embedded in otherwise noisy filenames.
    for alias, full_name in aliases.items():
        alias_norm = normalize_text(alias)
        if alias_norm and re.search(rf"(?<!\\w){re.escape(alias_norm.lower())}(?!\\w)", lowered):
            return normalize_text(full_name)

    noise = {
        "igcse", "arabic", "cie", "cambridge", "book", "pdf", "review", "reviewed",
        "comment", "comments", "final", "copy", "version", "part", "workbook", "student",
        "teacher", "2p", "v2", "v3",
    }
    tokens = [t for t in normalized.split() if t]
    kept = [
        t for t in tokens
        if t.lower() not in noise and not re.fullmatch(r"\\d+", t)
        and t.lower() not in generic_values
    ]
    candidate = " ".join(kept).strip()
    return candidate if _looks_like_full_name(candidate, generic_values) and len(kept) <= 4 else ""


def reviewer_name(
    raw_author: str,
    explicit_reviewer: str,
    aliases: dict[str, str],
    generic_values: set[str] | None = None,
    source_filename: str = "",
) -> str:
    generic_values = generic_values or set()
    alias_lookup = {normalize_text(k).lower(): normalize_text(v) for k, v in aliases.items()}

    if explicit_reviewer:
        explicit = normalize_text(explicit_reviewer)
        if _looks_like_full_name(explicit, generic_values):
            return explicit

    raw = normalize_text(raw_author)
    mapped = alias_lookup.get(raw.lower())
    if mapped:
        return mapped
    if _looks_like_full_name(raw, generic_values):
        return raw

    if source_filename:
        return _filename_reviewer_candidate(source_filename, aliases, generic_values)
    return ""

def annotation_fingerprint(reviewer: str, book_page: str, annotation_type: str, comment: str, selected_text: str, rect: fitz.Rect) -> str:
    material = "|".join(
        [
            normalize_text(reviewer),
            str(book_page),
            annotation_type,
            normalize_text(comment),
            normalize_text(selected_text),
            f"{round(rect.x0,1)},{round(rect.y0,1)},{round(rect.x1,1)},{round(rect.y1,1)}",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def identity_key(reviewer: str, book_page: str, annotation_id: str, fallback: str) -> str:
    if annotation_id:
        basis = f"native|{normalize_text(reviewer)}|{book_page}|{annotation_id.strip()}"
    else:
        basis = f"fallback|{fallback}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def should_import(annotation_type: str, comment: str, rules: dict[str, str]) -> tuple[bool, str]:
    if normalize_text(comment):
        return True, ""
    action = rules.get(annotation_type, rules.get("default", "keep"))
    if action == "skip":
        return False, f"empty_{annotation_type.lower()}"
    return True, ""


def extract_pdf(
    pdf_path: Path,
    config: dict[str, Any],
    master_index: dict[str, dict[str, Any]] | None = None,
    explicit_reviewer: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    digest = sha256_file(pdf_path)
    doc = fitz.open(pdf_path)
    rows: list[dict[str, Any]] = []
    aliases = config.get("reviewer_aliases", {})
    generic_values = {normalize_text(v).lower() for v in config.get("generic_author_values", [])}
    empty_rules = config.get("empty_annotation_rules", {"default": "keep"})
    mapped_pages = 0
    unresolved_pages = set()

    for pno, page in enumerate(doc, start=1):
        book_page, mapping_method, mapping_confidence, footer_page_candidate, footer_status = infer_book_page(page, pno, master_index)
        if book_page:
            mapped_pages += 1
        else:
            unresolved_pages.add(pno)

        annot = page.first_annot
        while annot:
            info = annot.info or {}
            raw_author = (info.get("title") or "").strip()
            reviewer = reviewer_name(raw_author, explicit_reviewer, aliases, generic_values, pdf_path.name)
            annotation_id = (info.get("id") or "").strip()
            comment = info.get("content") or ""
            selected = marked_text(page, annot)
            annotation_type = annot.type[1]
            rect = annot.rect
            fallback = annotation_fingerprint(
                reviewer, book_page, annotation_type, comment, selected, rect
            )
            key = identity_key(reviewer, book_page, annotation_id, fallback)
            keep, skip_reason = should_import(annotation_type, comment, empty_rules)
            try:
                reply_to_xref = annot.irt_xref or ""
            except Exception:
                reply_to_xref = ""

            rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "source_file": pdf_path.name,
                    "source_sha256": digest,
                    "reviewer": reviewer,
                    "raw_author": raw_author,
                    "pdf_page": pno,
                    "book_page": book_page,
                    "mapping_method": mapping_method,
                    "mapping_confidence": mapping_confidence,
                    "footer_page_candidate": footer_page_candidate,
                    "footer_status": footer_status,
                    "annotation_type": annotation_type,
                    "comment": comment,
                    "selected_text": selected,
                    "subject": (info.get("subject") or "").strip(),
                    "created": pdf_date(info.get("creationDate") or ""),
                    "modified": pdf_date(info.get("modDate") or ""),
                    "annotation_id": annotation_id,
                    "identity_key": key,
                    "fallback_fingerprint": fallback,
                    "xref": annot.xref,
                    "reply_to_xref": reply_to_xref,
                    "rect_x0": round(rect.x0, 3),
                    "rect_y0": round(rect.y0, 3),
                    "rect_x1": round(rect.x1, 3),
                    "rect_y1": round(rect.y1, 3),
                    "is_empty": not bool(normalize_text(comment)),
                    "import_candidate": keep,
                    "skip_reason": skip_reason,
                }
            )
            annot = annot.next

    page_count = doc.page_count
    doc.close()
    summary = {
        "schema_version": SCHEMA_VERSION,
        "pdf": pdf_path.name,
        "sha256": digest,
        "pages": page_count,
        "pages_mapped": mapped_pages,
        "pages_unresolved": sorted(unresolved_pages),
        "footer_mismatches": sorted({r["pdf_page"] for r in rows if r.get("footer_status") == "footer_mismatch"}),
        "annotations_found": len(rows),
        "import_candidates": sum(bool(r["import_candidate"]) for r in rows),
        "skipped": sum(not bool(r["import_candidate"]) for r in rows),
        "skipped_by_reason": {},
        "reviewers": sorted({r["reviewer"] for r in rows if r["reviewer"]}),
        "book_pages_with_annotations": sorted(
            {str(r["book_page"]) for r in rows if r["book_page"]},
            key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x),
        ),
    }
    for row in rows:
        if row["skip_reason"]:
            summary["skipped_by_reason"][row["skip_reason"]] = summary["skipped_by_reason"].get(row["skip_reason"], 0) + 1
    return rows, summary


def write_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], outdir: Path) -> tuple[Path, Path, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    stem = Path(summary["pdf"]).stem
    json_path = outdir / f"{stem}.annotations.json"
    csv_path = outdir / f"{stem}.annotations.csv"
    summary_path = outdir / f"{stem}.summary.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Workflow 2 native PDF annotation extractor")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--master", type=Path, help="Full master PDF used for page fingerprint mapping")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--reviewer", default="", help="Explicit normalized reviewer name")
    parser.add_argument("--outdir", type=Path, default=Path(__file__).with_name("output"))
    args = parser.parse_args()

    config = load_config(args.config)
    master_index = build_master_index(args.master) if args.master else None
    rows, summary = extract_pdf(args.pdf, config, master_index, args.reviewer)
    paths = write_outputs(rows, summary, args.outdir)
    summary["outputs"] = [str(p) for p in paths]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
