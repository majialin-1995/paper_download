#!/usr/bin/env python3
"""
根据 summaries 目录生成演示文稿（占位符替换版）
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List

try:
    from pptx import Presentation
except Exception:
    Presentation = None


# ───────────────────────── 参数解析 ───────────────────────── #

def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser("根据 summaries 生成 PPT（占位符版）")
    p.add_argument("summaries", type=Path, help="包含 JSON 摘要的目录")
    p.add_argument(
        "--template", type=Path, default=Path("template.pptx"),
        help="PPT 模板文件路径"
    )
    p.add_argument(
        "--out", type=Path, default=Path("slides.pptx"),
        help="输出 PPT 文件名"
    )
    # 这里先设为 None，后面解析完再动态指定默认路径
    p.add_argument(
        "--refs", type=Path, default=None,
        help="参考文献文本（每行一条）。默认：summaries 上级目录的 references_ieee.txt"
    )
    p.add_argument(
        "--print-info", action="store_true",
        help="仅打印摘要信息，不生成 PPT"
    )

    args = p.parse_args(argv)

    # 动态设置默认 refs
    if args.refs is None:
        args.refs = args.summaries.parent / "references_ieee.txt"

    return args


# ─────────────────────── 工具函数 ─────────────────────── #

def find_reference(title: str, refs: List[str]) -> str:
    norm = re.sub(r"[^\w\s]", "", title).lower()
    for line in refs:
        if norm in re.sub(r"[^\w\s]", "", line).lower():
            return line
    return ""


def duplicate_slide(prs, slide):
    new_slide = prs.slides.add_slide(slide.slide_layout)
    for shp in slide.shapes:
        el = shp.element
        new_el = copy.deepcopy(el)
        new_slide.shapes._spTree.insert_element_before(new_el, 'p:extLst')
    return new_slide


# ①②③… 生成器
CIRCLES = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩",
           "⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳"]

def indexed_text(lst: List[Any] | None) -> str:
    """
    把 List[str] 转成：
      ① 内容
      ② 内容
      ③ 内容
    """
    if not lst:
        return ""
    out = []
    for i, item in enumerate(lst):
        mark = CIRCLES[i] if i < len(CIRCLES) else f"({i+1})"
        out.append(f"{mark} {item}")
    return "\n".join(out)


# 现象仍然不编号，需要就告诉我
def plain_text(lst: List[Any] | None) -> str:
    if not lst:
        return ""
    return "\n".join(str(x) for x in lst)


# ─────────────────────── 占位符填充 ─────────────────────── #

def fill_placeholders(
    slide,
    data: Dict[str, Any],
    title: str,
    reference: str,
    page: int,
    total_pages: int,
    section: str,
    idx: int
) -> None:

    phenomenon = data.get("phenomenon") or []
    problems   = data.get("problem")    or []
    methods    = data.get("mechanism")  or []
    results    = data.get("result")     or []

    mapping: Dict[str, str] = {
        "{{No.}}":        str(idx),
        "{{title}}":      title,
        "{{reference}}":  reference or "",
        "{{Pages}}":      f"{page} / {total_pages}",
        "{{totalpages}}": str(total_pages),
    }
    
    if section == "intro":
        mapping["{{phenomenon}}"] = plain_text(phenomenon)   # 现象不编号
        mapping["{{problems}}"]   = indexed_text(problems)    # 编号 ①②③
        mapping["{{methods}}"]    = indexed_text(methods)     # 编号 ①②③

    elif section == "conclusion":
        mapping["{{results}}"]    = indexed_text(results)     # 编号 ①②③

    # 替换占位符
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                t = run.text
                for ph, val in mapping.items():
                    if ph in t:
                        t = t.replace(ph, val)
                run.text = t


# ───────────────────────── 主逻辑 ───────────────────────── #

def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)

    json_files = sorted(args.summaries.glob("*.json"))
    if not json_files:
        raise SystemExit(f"❌ 未在 {args.summaries} 找到任何 .json 文件")

    if args.print_info:
        refs = args.refs.read_text(encoding="utf-8").splitlines() if args.refs.is_file() else []
        for i, jf in enumerate(json_files, 1):
            data = json.loads(jf.read_text(encoding="utf-8"))
            title = jf.stem.split("_", 1)[1] if "_" in jf.stem else jf.stem
            ref = find_reference(title, refs)
            print(f"{i}. {title}")
            print(ref)
            print(json.dumps(data, ensure_ascii=False, indent=2), "\n")
        return

    if Presentation is None:
        raise SystemExit("请安装 python-pptx： pip install python-pptx")

    prs = Presentation(str(args.template))

    base_title = base_intro = base_conclusion = None

    # 找模板页
    for s in prs.slides:
        txt = "\n".join(sh.text for sh in s.shapes if sh.has_text_frame)
        if "{{title}}" in txt and base_title is None:
            base_title = s
        if "{{problems}}" in txt and "{{methods}}" in txt:
            base_intro = s
        if "{{results}}" in txt:
            base_conclusion = s

    if not all([base_title, base_intro, base_conclusion]):
        raise SystemExit("❌ 模板缺失 title/intro/conclusion 的任意一页")
    
    ref_lines = args.refs.read_text(encoding="utf-8").splitlines() if args.refs.is_file() else []

    template_slide_count = len(prs.slides)
    extra = 3
    total_pages = template_slide_count + extra * len(json_files)

    for idx, jf in enumerate(json_files, 1):
        data = json.loads(jf.read_text(encoding="utf-8"))
        title = jf.stem.split("_", 1)[1] if "_" in jf.stem else jf.stem
        reference = find_reference(title, ref_lines)

        page1 = template_slide_count + extra * (idx - 1) + 1
        page2 = page1 + 1
        page3 = page1 + 2

        slide1 = duplicate_slide(prs, base_title)
        fill_placeholders(slide1, data, title, reference, page1, total_pages, "title", idx)

        slide2 = duplicate_slide(prs, base_intro)
        fill_placeholders(slide2, data, title, reference, page2, total_pages, "intro", idx)

        slide3 = duplicate_slide(prs, base_conclusion)
        fill_placeholders(slide3, data, title, reference, page3, total_pages, "conclusion", idx)

    prs.save(args.out)
    print(f"✔ 已生成: {args.out}")


if __name__ == "__main__":
    main()
