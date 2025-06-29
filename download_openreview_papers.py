from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List

import openreview  # type: ignore
from pypdf import PdfReader          # ← NEW
from tqdm import tqdm

API_BASE_URL = "https://api2.openreview.net"

# ── Editable mapping from abbreviations to "Full Name (Abbr.)" ───────────────
VENUE_MAP: Dict[str, str] = {
    "ICLR": "International Conference on Learning Representations (ICLR)",
    "NeurIPS": "Conference on Neural Information Processing Systems (NeurIPS)",
    "ICML": "International Conference on Machine Learning (ICML)",
    "CVPR": "IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)",
    "ECCV": "European Conference on Computer Vision (ECCV)",
    "AAAI": "AAAI Conference on Artificial Intelligence (AAAI)",
    "ACL": "Annual Meeting of the Association for Computational Linguistics (ACL)",
    "EMNLP": "Conference on Empirical Methods in Natural Language Processing (EMNLP)",
}

###############################################################################
# CLI ARGUMENTS                                                               #
###############################################################################

def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download OpenReview PDFs (accepted by default) and output reference list.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--query", required=True,
                   help="Keyword (regex, case-insensitive) to match.")
    p.add_argument("--venues", nargs="+", required=True, metavar="VENUE_ID",
                   help="One or more OpenReview venue IDs, e.g. ICLR.cc/2025/Conference")
    p.add_argument("--out", type=Path, default=Path("runs"),
                   help="Base directory for search runs")
    p.add_argument("--run-name", dest="run_name",
                   help="Subdirectory name under --out; default timestamp")
    p.add_argument("--style", choices=["gb7714", "ieee"], default="gb7714",
                   help="Reference style to output.")
    p.add_argument("--max", type=int, default=None, help="Download at most N papers.")
    p.add_argument("--include-submitted", action="store_true",
                   help="Also include under-review / desk-rejected / withdrawn submissions.")
    return p.parse_args(argv)

###############################################################################
# OPENREVIEW CONNECTION                                                       #
###############################################################################

def connect_client() -> "openreview.api.OpenReviewClient":
    username = os.getenv("OPENREVIEW_USERNAME")
    password = os.getenv("OPENREVIEW_PASSWORD")
    if not (username and password):
        sys.exit("Error: please set OPENREVIEW_USERNAME & OPENREVIEW_PASSWORD env vars.")
    return openreview.api.OpenReviewClient(baseurl=API_BASE_URL, username=username, password=password)

###############################################################################
# FETCH NOTES                                                                 #
###############################################################################

def submission_invitation(client, venue_id: str) -> str:
    group = client.get_group(venue_id)
    sub_name = group.content["submission_name"]["value"]
    return f"{venue_id}/-/{sub_name}"


def iter_notes(client, venue_id: str, include_submitted: bool):
    """Yield accepted notes, optionally including submissions still under review."""
    # Accepted / officially published
    for note in client.get_all_notes(content={"venueid": venue_id}):
        yield note
    if include_submitted:
        # Add other statuses (under review, withdrawn, desk-rejected, etc.)
        invitation = submission_invitation(client, venue_id)
        seen = set()
        for note in client.get_all_notes(invitation=invitation):
            if note.id not in seen:  # avoid duplicates if status already accepted
                seen.add(note.id)
                yield note

###############################################################################
# UTILITIES                                                                   #
###############################################################################

def safe_filename(title: str, number: int) -> str:
    title = re.sub(r"[\\/*?:\"<>|]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return f"{number}_{title[:100]}.pdf"


def matches(note, pattern: re.Pattern[str]) -> bool:
    fields = [note.content["title"]["value"], note.content.get("abstract", {}).get("value", "")]
    return any(pattern.search(f) for f in fields)


def download_pdf(client, note, dest: Path) -> bool:
    try:
        data = client.get_attachment(id=note.id, field_name="pdf")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] PDF missing for {note.id}: {e}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True

# ── NEW: extract_pages with fallback to PDF ──────────────────────────────────
def extract_pages(info: dict, pdf_path: Path | None = None) -> str:
    """Return page range string; fallback to counting PDF pages."""
    # 1) venue-provided metadata
    for key in ("pages", "page_numbers", "page", "start_page"):
        if key in info and info[key].get("value"):
            return str(info[key]["value"]).strip()
    if {"start_page", "end_page"} <= info.keys():
        sp, ep = info["start_page"]["value"], info["end_page"]["value"]
        return f"{sp}-{ep}"
    # 2) count pages in the downloaded PDF
    if pdf_path and pdf_path.exists():
        try:
            n_pages = len(PdfReader(str(pdf_path)).pages)
            return f"1-{n_pages}"
        except Exception:
            pass
    return "n/a"

###############################################################################
# REFERENCE FORMATTING                                                        #
###############################################################################

def expand_venue_name(raw: str) -> str:
    for abbr, full in VENUE_MAP.items():
        if abbr.lower() in raw.lower():
            return full
    return raw


def join_ieee_authors(authors: List[str]) -> str:
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    return ", ".join(authors[:-1]) + f", and {authors[-1]}"


def first_n_authors(authors: List[str], n: int = 3) -> str:
    return "; ".join(authors) if len(authors) <= n else "; ".join(authors[:n]) + ", et al."


def gb7714_reference(note, idx: int, pages: str) -> str:
    info = note.content
    authors = first_n_authors(info.get("authors", {}).get("value", []))
    title = info["title"]["value"]
    venue = expand_venue_name(info.get("venue", {}).get("value") or info.get("venueid", {}).get("value") or "")
    year = info.get("year", {}).get("value") if "year" in info else _dt.datetime.fromtimestamp(note.cdate/1000).year
    pub_type = "[C]" if "Conference" in venue or "Proceedings" in venue else "[J]"
    return f"[{idx}] {authors}. {title}{pub_type}. {venue}, {year}, pp. {pages}."


def ieee_reference(note, idx: int, pages: str) -> str:
    info = note.content
    authors = join_ieee_authors(info.get("authors", {}).get("value", []))
    title = info["title"]["value"]
    raw_venue = info.get("venue", {}).get("value") or info.get("venueid", {}).get("value") or ""
    venue_full = expand_venue_name(raw_venue)
    venue_str = venue_full if venue_full.lower().startswith("in ") else f"in Proceedings of the {venue_full}"
    year = info.get("year", {}).get("value") if "year" in info else _dt.datetime.fromtimestamp(note.cdate/1000).year
    pages_part = f", pp. {pages}" if pages and pages != "n/a" else ""
    return f"{authors}, \"{title},\" {venue_str}, {year}{pages_part}."

###############################################################################
# MAIN                                                                        #
###############################################################################

def main(argv: List[str] | None = None):
    args = parse_args(argv)
    client = connect_client()
    regex = re.compile(args.query, re.IGNORECASE)
    formatter = ieee_reference if args.style == "ieee" else gb7714_reference

    run_name = args.run_name or _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.out / run_name
    pdf_root = run_dir / "papers"
    run_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "query": args.query,
        "venues": args.venues,
        "timestamp": run_name,
        "style": args.style,
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    references: List[str] = []
    downloaded = 0

    for venue in args.venues:
        print(f"\n>>> Scanning {venue} …")
        try:
            notes_iter = iter_notes(client, venue, args.include_submitted)
        except Exception as e:  # noqa: BLE001
            print(f"[error] Cannot fetch {venue}: {e}")
            continue

        for note in tqdm(notes_iter, unit="paper"):
            if args.max is not None and downloaded >= args.max:
                break
            if not matches(note, regex):
                continue

            filename = safe_filename(note.content["title"]["value"], note.number)
            pdf_path = pdf_root / venue.replace("/", "_") / filename

            # download (or skip if already there) …
            if pdf_path.exists() or download_pdf(client, note, pdf_path):
                downloaded += 1
                pages = extract_pages(note.content, pdf_path)
                references.append(formatter(note, len(references) + 1, pages))

    if references:
        ref_file = run_dir / f"references_{args.style}.txt"
        ref_file.write_text("\n".join(references), encoding="utf-8")
        print(f"\n✔ Saved {len(references)} references to {ref_file}")
    else:
        print("\nNo matching papers; no reference list generated.")

    print("Finished!", downloaded, "PDF(s) total. Run directory:", run_dir)


if __name__ == "__main__":
    main()