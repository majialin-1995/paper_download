#!/usr/bin/env python3
"""
download_openreview_papers.py  (v0.10 — 2025-11-14)

下载 *已正式发表* 的 OpenReview 论文 PDF，
生成 **BibTeX + RIS + 文本清单 (ieee / gb7714-2015 / ris)**。

与 v0.8 的主要差异：
- 使用 OpenReview 的 search_notes（Elasticsearch）在服务器端按关键词检索，
  不再对每个 venue 全量 get_all_notes；
- 保留本地 regex 二次筛选（兼容你原来的用法）；
- 增加了详细日志：每次保存 PDF / 引用时都会打印绝对路径，方便排查。
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
        description=(
            "Download OpenReview PDFs (accepted by default, via server-side search_notes) "
            "and output reference list."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--query",
        required=True,
        help="Keyword / regex (case-insensitive) to match in title / abstract.",
    )
    p.add_argument(
        "--venues",
        nargs="+",
        required=True,
        metavar="VENUE_ID",
        help="One or more OpenReview venue IDs, e.g. ICLR.cc/2025/Conference",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("runs"),
        help="Base directory for search runs",
    )
    p.add_argument(
        "--run-name",
        dest="run_name",
        help="Subdirectory name under --out; default timestamp",
    )
    p.add_argument(
        "--style",
        choices=["gb7714", "ieee"],
        default="gb7714",
        help="Which *extra* textual list to generate in addition to .bib & .ris.",
    )
    p.add_argument(
        "--max",
        type=int,
        default=None,
        help="Download at most N papers (across all venues).",
    )
    p.add_argument(
        "--include-submitted",
        action="store_true",
        help=(
            "Also include under-review / desk-rejected / withdrawn submissions. "
            "默认只保留已正式发表（content['venueid'] == VENUE_ID）的 note。"
        ),
    )
    return p.parse_args(argv)

# ─────────────────────────── OpenReview 连接 ────────────────────────────────
def connect_client() -> "openreview.api.OpenReviewClient":
    username = os.getenv("OPENREVIEW_USERNAME")
    password = os.getenv("OPENREVIEW_PASSWORD")
    if not (username and password):
        sys.exit("Error: please set OPENREVIEW_USERNAME & OPENREVIEW_PASSWORD env vars.")
    print(f"[info] Using OpenReview account: {username}")
    return openreview.api.OpenReviewClient(
        baseurl=API_BASE_URL, username=username, password=password
    )

# ──────────────────────────── 工具函数 ───────────────────────────────────────
def safe_filename(title: str, number: int | None) -> str:
    """把标题变成安全的文件名；number 可空。"""
    title = re.sub(r"[\\/*?:\"<>|]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    prefix = f"{int(number):03d}_" if isinstance(number, int) else ""
    return f"{prefix}{title[:100]}.pdf"

def matches(note, pattern: re.Pattern[str]) -> bool:
    """本地 regex 复核，兼容原有行为。"""
    content = note.content or {}
    title = content.get("title", {}).get("value", "") or ""
    abstract = content.get("abstract", {}).get("value", "") or ""
    return any(pattern.search(f) for f in (title, abstract))

def download_pdf(client, note, dest: Path) -> bool:
    try:
        data = client.get_attachment(id=note.id, field_name="pdf")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] PDF missing for {note.id}: {e}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"[save] PDF saved to: {dest.resolve()}")
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
        except Exception:  # noqa: BLE001
            pass
    return "n/a"

def expand_venue_name(raw: str) -> str:
    for abbr, full in VENUE_MAP.items():
        if abbr.lower() in raw.lower():
            return full
    return raw

# ──────────────── 在指定 venue 内用 search_notes 检索 ──────────────────────
def search_notes_in_venue(
    client: "openreview.api.OpenReviewClient",
    venue_id: str,
    term: str,
    include_submitted: bool,
    limit: int | None,
):
    """
    使用 Elasticsearch search_notes 在服务器端按关键词 + group 检索。
    """
    fetched = 0
    offset = 0
    MAX_BATCH = 1000  # search_notes 单次最多 1000 条

    while True:
        if limit is not None:
            remaining = limit - fetched
            if remaining <= 0:
                return
            batch_limit = min(remaining, MAX_BATCH)
        else:
            batch_limit = MAX_BATCH

        notes = client.search_notes(
            term=term,
            content="all",     # 在标题 / 摘要 / 关键词等全部内容里搜
            group=venue_id,    # 限定在该 venue group 下
            source="all",
            limit=batch_limit,
            offset=offset,
        )

        if not notes:
            return

        for note in notes:
            content = note.content or {}
            venueid = content.get("venueid", {}).get("value", "")

            if not include_submitted:
                # 默认：只要“已正式发表”的 note
                if venueid != venue_id:
                    continue

            fetched += 1
            yield note
            if limit is not None and fetched >= limit:
                return

        offset += len(notes)

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
    info = note.content or {}
    authors = first_n_authors(info.get("authors", {}).get("value", []))
    title = info.get("title", {}).get("value", "")
    venue = expand_venue_name(
        info.get("venue", {}).get("value")
        or info.get("venueid", {}).get("value")
        or ""
    )
    if "year" in info:
        year = info["year"]["value"]
    else:
        year = _dt.datetime.fromtimestamp(note.cdate / 1000).year + 1
    pub_type = "[C]" if "Conference" in venue or "Proceedings" in venue else "[J]"
    pp = f", pp. {pages}" if pages and pages != "n/a" else ""
    return f"[{idx}] {authors}. {title}{pub_type}. {venue}, {year}{pp}."

def ieee_reference(note, idx: int, pages: str) -> str:
    info = note.content or {}
    authors = join_ieee_authors(info.get("authors", {}).get("value", []))
    title = info.get("title", {}).get("value", "")
    venue_full = expand_venue_name(
        info.get("venue", {}).get("value")
        or info.get("venueid", {}).get("value")
        or ""
    )
    venue_str = venue_full if venue_full.lower().startswith("in ") \
        else f"in Proceedings of the {venue_full}"
    if "year" in info:
        year = info["year"]["value"]
    else:
        year = _dt.datetime.fromtimestamp(note.cdate / 1000).year + 1
    pp = f", pp. {pages}" if pages and pages != "n/a" else ""
    return f"{authors}, \"{title},\" {venue_str}, {year}{pp}."

# ──────────────────────────── RIS / BibTeX ──────────────────────────────────
def ris_reference(note, idx: int, pages: str) -> str:
    info = note.content or {}
    authors = info.get("authors", {}).get("value", [])
    title = info.get("title", {}).get("value", "")
    venue = expand_venue_name(
        info.get("venue", {}).get("value")
        or info.get("venueid", {}).get("value")
        or ""
    )
    if "year" in info:
        year = info["year"]["value"]
    else:
        year = _dt.datetime.fromtimestamp(note.cdate / 1000).year + 1
    url = f"https://openreview.net/forum?id={note.id}"
    ty = "CONF" if "Conference" in venue or "Proceedings" in venue else "JOUR"

    ris = [f"TY  - {ty}"]
    for au in authors:
        ris.append(f"AU  - {au}")
    ris.extend(
        [
            f"TI  - {title}",
            f"PY  - {year}",
        ]
    )
    if pages and pages != "n/a":
        ris.append(f"SP  - {pages}")
    abstract = info.get("abstract", {}).get("value")
    if abstract:
        ris.append(f"AB  - {abstract}")
    ris.extend(
        [
            f"T2  - {venue}",
            f"UR  - {url}",
            "ER  -",
        ]
    )
    return "\n".join(ris)

def bib_reference(note, pages: str) -> str:
    info = note.content or {}
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
    title = info.get("title", {}).get("value", "")
    venue = expand_venue_name(
        info.get("venue", {}).get("value")
        or info.get("venueid", {}).get("value")
        or ""
    )
    if "year" in info:
        year = info["year"]["value"]
    else:
        year = _dt.datetime.fromtimestamp(note.cdate / 1000).year + 1
    url = f"https://openreview.net/forum?id={note.id}"
    key = re.sub(
        r"\W+",
        "",
        (authors.split(" ")[-1] if authors else "paper") + str(year),
    )
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
        "gb7714": gb7714_reference,
    }[args.style]

    run_name = args.run_name or _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = (args.out / run_name).resolve()
    pdf_root = run_dir / "papers"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[info] Run directory: {run_dir}")

    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "query": args.query,
                "venues": args.venues,
                "timestamp": run_name,
                "style": args.style,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[save] meta.json written to: {(run_dir / 'meta.json').resolve()}")

    txt_refs: List[str] = []
    bib_refs: List[str] = []
    ris_refs: List[str] = []
    downloaded = 0

    for venue in args.venues:
        print(f"\n>>> Scanning {venue} (via search_notes) …")

        # 为当前 venue 计算还可以下载多少篇
        per_venue_limit = None
        if args.max is not None:
            remaining = args.max - downloaded
            if remaining <= 0:
                break
            per_venue_limit = remaining

        try:
            notes_iter = search_notes_in_venue(
                client=client,
                venue_id=venue,
                term=args.query,
                include_submitted=args.include_submitted,
                limit=per_venue_limit,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[error] Cannot search {venue}: {e}")
            continue

        for note in tqdm(list(notes_iter), unit="paper"):
            if args.max is not None and downloaded >= args.max:
                break

            # 本地再做一遍 regex 过滤，兼容原有“正则匹配标题/摘要”的语义
            if not matches(note, regex):
                continue

            title = note.content.get("title", {}).get("value", "untitled")
            number = getattr(note, "number", None)
            filename = safe_filename(title, number)
            pdf_path = pdf_root / venue.replace("/", "_") / filename

            if pdf_path.exists() or download_pdf(client, note, pdf_path):
                downloaded += 1
                pages = extract_pages(note.content, pdf_path)

                bib_entry = bib_reference(note, pages)
                ris_entry = ris_reference(note, len(ris_refs) + 1, pages)
                txt_entry = txt_formatter(note, len(txt_refs) + 1, pages)

                bib_refs.append(bib_entry)
                ris_refs.append(ris_entry)
                txt_refs.append(txt_entry)

                print(f"[ref] Added entry #{len(bib_refs)} for note {note.id}")
            else:
                print(f"[warn] Skip note {note.id} because PDF not available.")

            if args.max is not None and downloaded >= args.max:
                break

    # ───────────── 文件写出 ───────────────────────────────────────────────
    if bib_refs:
        bib_path = (run_dir / "references.bib").resolve()
        (run_dir / "references.bib").write_text(
            "\n\n".join(bib_refs), encoding="utf-8"
        )
        print(f"[save] BibTeX written to: {bib_path}")
    if ris_refs:
        ris_path = (run_dir / "references.ris").resolve()
        (run_dir / "references.ris").write_text(
            "\n\n".join(ris_refs), encoding="utf-8"
        )
        print(f"[save] RIS written to: {ris_path}")
    if txt_refs:
        fname = f"references_{args.style}.txt"
        txt_path = (run_dir / fname).resolve()
        (run_dir / fname).write_text("\n".join(txt_refs), encoding="utf-8")
        print(f"[save] Text refs written to: {txt_path}")

    if any([bib_refs, ris_refs, txt_refs]):
        print(
            f"\n✔ Saved {len(bib_refs)} BibTeX, {len(ris_refs)} RIS "
            f"and {len(txt_refs)} {args.style.upper()} entries → {run_dir}"
        )
    else:
        print("\nNo matching papers; nothing generated.")

if __name__ == "__main__":
    main()
