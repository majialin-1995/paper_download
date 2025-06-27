#!/usr/bin/env python3
"""
 download_openreview_papers.py (v0.4 – 2025-06-28)
 -------------------------------------------------
 Download PDFs from OpenReview that match a keyword **and** generate a
 reference list in either **GB/T 7714-2015 numeric** or **IEEE conference**
 style (example provided by user).

 CHANGELOG
 =========
 • **v0.4** – Add `--style` option ("gb7714" | "ieee").  Default: gb7714.
              Generates `references_<style>.txt` accordingly.
 • v0.3 – GB/T 7714 references.
 • v0.2 – Fix empty `details` bug.
 • v0.1 – Initial release.

 QUICK START
 ===========
 ```bash
 export OPENREVIEW_USERNAME="you@example.com"
 export OPENREVIEW_PASSWORD="your_password"
 pip install openreview-py tqdm

 # IEEE-style reference list
 python download_openreview_papers.py --query "reinforcement learning" --venues ICLR.cc/2025/Conference NeurIPS.cc/2024/Conference --style ieee --out papers
 ```
"""
from __future__ import annotations 

import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path
from typing import List

import openreview  # type: ignore
from tqdm import tqdm

API_BASE_URL = "https://api2.openreview.net"

###############################################################################
# CLI ARGUMENTS                                                               #
###############################################################################

def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download OpenReview PDFs and output reference list.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--query", required=True, help="Keyword (regex, case-insensitive) to match.")
    p.add_argument("--venues", nargs="+", required=True, metavar="VENUE_ID",
                   help="One or more OpenReview venue IDs, e.g. ICLR.cc/2025/Conference")
    p.add_argument("--out", type=Path, default=Path("papers"), help="Directory to save PDFs.")
    p.add_argument("--style", choices=["gb7714", "ieee"], default="gb7714",
                   help="Reference style to output.")
    p.add_argument("--max", type=int, default=None, help="Download at most N papers.")
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
# HELPERS                                                                     #
###############################################################################

def submission_invitation(client, venue_id: str) -> str:
    group = client.get_group(venue_id)
    sub_name = group.content["submission_name"]["value"]
    return f"{venue_id}/-/{sub_name}"


def iter_submissions(client, venue_id: str):
    return client.get_all_notes(invitation=submission_invitation(client, venue_id))


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

###############################################################################
# REFERENCE FORMATTING                                                        #
###############################################################################

def join_ieee_authors(authors: List[str]) -> str:
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    return ", ".join(authors[:-1]) + f", and {authors[-1]}"


def first_n_authors(authors: List[str], n: int = 3) -> str:
    if len(authors) <= n:
        return "; ".join(authors)
    return "; ".join(authors[:n]) + ", et al."


def gb7714_reference(note, idx: int) -> str:
    info = note.content
    authors = info.get("authors", {}).get("value", [])
    authors_str = first_n_authors(authors)
    title = info["title"]["value"]
    venue = info.get("venue", {}).get("value") or info.get("venueid", {}).get("value") or ""
    year = info.get("year", {}).get("value") if "year" in info else _dt.datetime.fromtimestamp(note.cdate/1000).year
    pub_type = "[C]" if "Conference" in venue or "Proceedings" in venue else "[J]"
    return f"[{idx}] {authors_str}. {title}{pub_type}. {venue}, {year}."


def ieee_reference(note, idx: int) -> str:
    info = note.content
    authors = info.get("authors", {}).get("value", [])
    authors_str = join_ieee_authors(authors)
    title = info["title"]["value"]
    # Venue: try explicit fields first
    venue = info.get("venue", {}).get("value") or info.get("venueid", {}).get("value") or ""
    # Ensure "in Proc." prefix if venue resembles a conference
    if venue and not venue.lower().startswith("in "):
        venue_str = f"in Proc. {venue}"
    else:
        venue_str = venue
    year = info.get("year", {}).get("value") if "year" in info else _dt.datetime.fromtimestamp(note.cdate/1000).year
    pages = info.get("pages", {}).get("value", "")
    pages_part = f", pp. {pages}" if pages else ""
    return f"{authors_str}, \"{title},\" {venue_str}, {year}{pages_part}."

###############################################################################
# MAIN                                                                        #
###############################################################################

def main(argv: List[str] | None = None):
    args = parse_args(argv)
    client = connect_client()
    regex = re.compile(args.query, re.IGNORECASE)

    references: List[str] = []
    downloaded = 0
    formatter = ieee_reference if args.style == "ieee" else gb7714_reference

    for venue in args.venues:
        print(f"\n>>> Scanning {venue} …")
        try:
            subs = iter_submissions(client, venue)
        except Exception as e:  # noqa: BLE001
            print(f"[error] Cannot fetch {venue}: {e}")
            continue

        for note in tqdm(subs, unit="paper"):
            if args.max is not None and downloaded >= args.max:
                break
            if not matches(note, regex):
                continue

            filename = safe_filename(note.content["title"]["value"], note.number)
            pdf_path = args.out / venue.replace("/", "_") / filename
            if pdf_path.exists() or download_pdf(client, note, pdf_path):
                downloaded += 1
                references.append(formatter(note, len(references)+1))

    # ── Write reference list ────────────────────────────────────────────────
    if references:
        ref_file = args.out / f"references_{args.style}.txt"
        ref_file.parent.mkdir(parents=True, exist_ok=True)
        ref_file.write_text("\n".join(references), encoding="utf-8")
        print(f"\n✔ Saved {len(references)} references to {ref_file}")
    else:
        print("\nNo matching papers; no reference list generated.")

    print("Finished!", downloaded, "PDF(s) total.")


if __name__ == "__main__":
    main()
