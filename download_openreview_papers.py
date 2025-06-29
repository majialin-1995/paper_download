#!/usr/bin/env python3
"""
download_openreview_papers.py  (v0.8 — 2025-06-29)

下载 *已正式发表* 的 OpenReview 论文 PDF，
生成 **BibTeX + RIS + 文本清单 (ieee / gb7714-2015 / ris)**。

用法示例
--------
python download_openreview_papers.py \
    --query "offline reinforcement learning" \
    --venues ICLR.cc/2025/Conference NeurIPS.cc/2024/Conference \
    --out runs --style ieee --max 40
"""
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
from pypdf import PdfReader
from tqdm import tqdm

API_BASE_URL = "https://api2.openreview.net"

# ───────────────────────────────── Venue 映射 ────────────────────────────────
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

# ────────────────────────────── CLI ─────────────────────────────────────────
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
    p.add_argument("--style", choices=["gb7714", "ieee", "ris"], default="gb7714",
                   help="Which *extra* textual list to generate in addition to .bib & .ris.")
    p.add_argument("--max", type=int, default=None, help="Download at most N papers.")
    p.add_argument("--include-submitted", action="store_true",
                   help="Also include under-review / desk-rejected / withdrawn submissions.")
    return p.parse_args(argv)

# ─────────────────────────── OpenReview 连接 ────────────────────────────────
def connect_client() -> "openreview.api.OpenReviewClient":
    username = os.getenv("OPENREVIEW_USERNAME")
    password = os.getenv("OPENREVIEW_PASSWORD")
    if not (username and password):
        sys.exit("Error: please set OPENREVIEW_USERNAME & OPENREVIEW_PASSWORD env vars.")
    return openreview.api.OpenReviewClient(baseurl=API_BASE_URL, username=username, password=password)

# ──────────────────────────── 迭代笔记 ───────────────────────────────────────
def submission_invitation(client, venue_id: str) -> str:
    group = client.get_group(venue_id)
    sub_name = group.content["submission_name"]["value"]
    return f"{venue_id}/-/{sub_name}"

def iter_notes(client, venue_id: str, include_submitted: bool):
    for note in client.get_all_notes(content={"venueid": venue_id}):
        yield note
    if include_submitted:
        invitation = submission_invitation(client, venue_id)
        seen = set()
        for note in client.get_all_notes(invitation=invitation):
            if note.id not in seen:
                seen.add(note.id)
                yield note

# ──────────────────────────── 工具函数 ───────────────────────────────────────
def safe_filename(title: str, number: int) -> str:
    title = re.sub(r"[\\/*?:\"<>|]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return f"{number}_{title[:100]}.pdf"

def matches(note, pattern: re.Pattern[str]) -> bool:
    fields = [note.content["title"]["value"],
              note.content.get("abstract", {}).get("value", "")]
    return any(pattern.search(f) for f in fields)

def download_pdf(client, note, dest: Path) -> bool:
    try:
        data = client.get_attachment(id=note.id, field_name="pdf")
    except Exception as e:
        print(f"[warn] PDF missing for {note.id}: {e}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True

def extract_pages(info: dict, pdf_path: Path | None = None) -> str:
    for key in ("pages", "page_numbers", "page", "start_page"):
        if key in info and info[key].get("value"):
            return str(info[key]["value"]).strip()
    if {"start_page", "end_page"} <= info.keys():
        sp, ep = info["start_page"]["value"], info["end_page"]["value"]
        return f"{sp}-{ep}"
    if pdf_path and pdf_path.exists():
        try:
            n_pages = len(PdfReader(str(pdf_path)).pages)
            return f"1-{n_pages}"
        except Exception:
            pass
    return "n/a"

def expand_venue_name(raw: str) -> str:
    for abbr, full in VENUE_MAP.items():
        if abbr.lower() in raw.lower():
            return full
    return raw

# ──────────────────── 文本清单 (IEE / GB-T 7714) ────────────────────────────
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
    venue = expand_venue_name(info.get("venue", {}).get("value") or
                              info.get("venueid", {}).get("value") or "")
    year = info.get("year", {}).get("value") if "year" in info \
        else _dt.datetime.fromtimestamp(note.cdate / 1000).year+1
    pub_type = "[C]" if "Conference" in venue or "Proceedings" in venue else "[J]"
    pp = f", pp. {pages}" if pages and pages != "n/a" else ""
    return f"[{idx}] {authors}. {title}{pub_type}. {venue}, {year}{pp}."

def ieee_reference(note, idx: int, pages: str) -> str:
    info = note.content
    authors = join_ieee_authors(info.get("authors", {}).get("value", []))
    title = info["title"]["value"]
    venue_full = expand_venue_name(info.get("venue", {}).get("value") or
                                   info.get("venueid", {}).get("value") or "")
    venue_str = venue_full if venue_full.lower().startswith("in ") \
        else f"in Proceedings of the {venue_full}"
    year = info.get("year", {}).get("value") if "year" in info \
        else _dt.datetime.fromtimestamp(note.cdate / 1000).year+1
    pp = f", pp. {pages}" if pages and pages != "n/a" else ""
    return f"{authors}, \"{title},\" {venue_str}, {year}{pp}."

# ──────────────────────────── RIS / BibTeX ──────────────────────────────────
def ris_reference(note, idx: int, pages: str) -> str:
    info = note.content
    authors = info.get("authors", {}).get("value", [])
    title = info["title"]["value"]
    venue = expand_venue_name(info.get("venue", {}).get("value") or
                              info.get("venueid", {}).get("value") or "")
    year = info.get("year", {}).get("value") if "year" in info \
        else _dt.datetime.fromtimestamp(note.cdate / 1000).year+1
    url = f"https://openreview.net/forum?id={note.id}"
    ty = "CONF" if "Conference" in venue or "Proceedings" in venue else "JOUR"

    ris = [f"TY  - {ty}"]
    for au in authors:
        ris.append(f"AU  - {au}")
    ris.extend([
        f"TI  - {title}",
        f"PY  - {year}",
    ])
    if pages and pages != "n/a":
        ris.append(f"SP  - {pages}")
    abstract = info.get("abstract", {}).get("value")
    if abstract:
        ris.append(f"AB  - {abstract}")
    ris.extend([
        f"T2  - {venue}",
        f"UR  - {url}",
        "ER  -"
    ])
    return "\n".join(ris)

def bib_reference(note, pages: str) -> str:
    info = note.content
    abstract = info.get("abstract", {}).get("value", "")
    # 若 _bibtex 已存在 → 复用
    if "_bibtex" in info and info["_bibtex"]["value"].strip().startswith("@"):
        entry = info["_bibtex"]["value"].rstrip().rstrip("}")
        # 若已有 abstract / pages 则不重复添加
        if abstract and not re.search(r"\babstract\s*=", entry, re.I):
            entry += f",\n  abstract = {{{abstract}}}"
        if pages not in ("", "n/a") and not re.search(r"\bpages\s*=", entry, re.I):
            entry += f",\n  pages    = {{{pages}}}"
        return entry + "\n}"
    # 否则手动拼装
    authors = " and ".join(info.get("authors", {}).get("value", []))
    title = info["title"]["value"]
    venue = expand_venue_name(info.get("venue", {}).get("value") or
                              info.get("venueid", {}).get("value") or "")
    year = info.get("year", {}).get("value") if "year" in info \
        else _dt.datetime.fromtimestamp(note.cdate / 1000).year+1
    url = f"https://openreview.net/forum?id={note.id}"
    key = re.sub(r"\W+", "", authors.split(" ")[-1] + str(year))
    lines = [
        f"@inproceedings{{{key},",
        f"  title     = {{{title}}},",
        f"  author    = {{{authors}}},",
        f"  booktitle = {{{venue}}},",
        f"  year      = {{{year}}},",
    ]
    if pages not in ("", "n/a"):
        lines.append(f"  pages     = {{{pages}}},")
    if abstract:
        lines.append(f"  abstract  = {{{abstract}}},")
    lines.append(f"  url       = {{{url}}}")
    lines.append("}")
    return "\n".join(lines)

# ──────────────────────────────── MAIN ──────────────────────────────────────
def main(argv: List[str] | None = None):
    args = parse_args(argv)
    client = connect_client()
    regex = re.compile(args.query, re.IGNORECASE)

    # txt-formatter 由 --style 决定
    txt_formatter = {
        "ieee": ieee_reference,
        "ris": lambda n, i, p: "",      # 若 --style=ris 不再生成 txt
        "gb7714": gb7714_reference,
    }[args.style]

    run_name = args.run_name or _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.out / run_name
    pdf_root = run_dir / "papers"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "meta.json").write_text(
        json.dumps({
            "query": args.query,
            "venues": args.venues,
            "timestamp": run_name,
            "style": args.style,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    txt_refs, bib_refs, ris_refs = [], [], []
    downloaded = 0

    for venue in args.venues:
        print(f"\n>>> Scanning {venue} …")
        try:
            notes_iter = iter_notes(client, venue, args.include_submitted)
        except Exception as e:
            print(f"[error] Cannot fetch {venue}: {e}")
            continue

        for note in tqdm(notes_iter, unit="paper"):
            if args.max is not None and downloaded >= args.max:
                break
            if not matches(note, regex):
                continue

            filename = safe_filename(note.content["title"]["value"], note.number)
            pdf_path = pdf_root / venue.replace("/", "_") / filename

            if pdf_path.exists() or download_pdf(client, note, pdf_path):
                downloaded += 1
                pages = extract_pages(note.content, pdf_path)

                # BibTeX & RIS（始终生成）
                bib_refs.append(bib_reference(note, pages))
                ris_refs.append(ris_reference(note, len(ris_refs) + 1, pages))

                # 可选的 txt-style
                if args.style != "ris":
                    txt_refs.append(txt_formatter(note, len(txt_refs) + 1, pages))

            if args.max is not None and downloaded >= args.max:
                break

    # ───────────── 文件写出 ───────────────────────────────────────────────
    if bib_refs:
        (run_dir / "references.bib").write_text("\n\n".join(bib_refs), encoding="utf-8")
    if ris_refs:
        (run_dir / "references.ris").write_text("\n\n".join(ris_refs), encoding="utf-8")
    if txt_refs:
        fname = f"references_{args.style}.txt"
        (run_dir / fname).write_text("\n".join(txt_refs), encoding="utf-8")

    if any([bib_refs, ris_refs, txt_refs]):
        print(f"\n✔ Saved {len(bib_refs)} BibTeX, {len(ris_refs)} RIS "
              f"and {len(txt_refs)} {args.style.upper()} entries → {run_dir}")
    else:
        print("\nNo matching papers; nothing generated.")

if __name__ == "__main__":
    main()
