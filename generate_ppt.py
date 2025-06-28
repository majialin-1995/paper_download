#!/usr/bin/env python3
"""根据 summaries 目录生成演示文稿"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

try:  # pptx is only required when generating PPT
    from pptx import Presentation  # type: ignore
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt
except Exception:  # pragma: no cover - optional dependency
    Presentation = None  # type: ignore
    PP_ALIGN = None  # type: ignore
    Inches = Pt = None  # type: ignore

# ---------------------------------------------------------------------------
# 原脚本包含调用大模型翻译的代码。本次修改仅保留生成 PPT 的功能，并
# 新增打印论文信息的选项，因此移除了与大模型相关的依赖与函数。
# ---------------------------------------------------------------------------


def find_reference(title: str, refs: List[str]) -> str:
    """在参考文献列表中查找给定标题对应的条目。"""
    norm = re.sub(r"[^\w\s]", "", title).lower()
    for line in refs:
        if norm in re.sub(r"[^\w\s]", "", line).lower():
            return line
    return ""


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser("根据 summaries 生成 PPT")
    p.add_argument("summaries", type=Path, help="包含 JSON 摘要的目录")
    p.add_argument("--template", type=Path, default=Path("template.pptx"),
                   help="PPT 模板 (default: template.pptx)")
    p.add_argument("--out", type=Path, default=Path("slides.pptx"),
                   help="输出文件名")
    p.add_argument("--refs", type=Path,
                   default=Path("papers/references_ieee.txt"),
                   help="参考文献文件 (default: papers/references_ieee.txt)")
    p.add_argument("--print-info", action="store_true",
                   help="仅打印摘要信息，不生成 PPT")
    return p.parse_args(argv)


def add_slide(prs: Presentation, title: str, data: Dict[str, Any], num: int) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    body = slide.shapes.placeholders[1].text_frame
    body.text = f"现象：{data.get('phenomenon', '')}"

    problems = data.get("problem")
    if problems:
        body.add_paragraph("问题：")
        for item in problems:
            body.add_paragraph(str(item), level=1)

    mechanisms = data.get("mechanism")
    if mechanisms:
        body.add_paragraph("机制：")
        for item in mechanisms:
            body.add_paragraph(str(item), level=1)

    result = data.get("result")
    if result:
        body.add_paragraph("结果：")
        if isinstance(result, dict):
            datasets = result.get("datasets")
            if datasets:
                body.add_paragraph("数据集：" + ", ".join(datasets), level=1)
            perf = result.get("performance")
            if isinstance(perf, list):
                for it in perf:
                    body.add_paragraph(str(it), level=1)
            elif isinstance(perf, dict):
                for k, v in perf.items():
                    body.add_paragraph(f"{k}: {v}", level=1)
        elif isinstance(result, list):
            for it in result:
                body.add_paragraph(str(it), level=1)

    # 页码文本框
    left = prs.slide_width - Inches(1)
    top = prs.slide_height - Inches(0.5)
    box = slide.shapes.add_textbox(left, top, Inches(1), Inches(0.4))
    tf = box.text_frame
    p = tf.paragraphs[0]
    p.text = str(num)
    p.alignment = PP_ALIGN.RIGHT
    p.runs[0].font.size = Pt(12)



def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)

    if args.print_info:
        refs: List[str] = []
        if args.refs.is_file():
            refs = args.refs.read_text(encoding="utf-8").splitlines()
        for idx, json_file in enumerate(sorted(args.summaries.glob("*.json")), 1):
            data = json.loads(json_file.read_text(encoding="utf-8"))
            title = json_file.stem.split("_", 1)[1] if "_" in json_file.stem else json_file.stem
            ref = find_reference(title, refs)
            print(f"{idx}. {title}")
            if ref:
                print(ref)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            print()
        return

    if Presentation is None:
        raise SystemExit("python-pptx is required to generate slides")

    prs = Presentation(str(args.template))

    for idx, json_file in enumerate(sorted(args.summaries.glob("*.json")), 1):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        add_slide(prs, json_file.stem, data, idx)

    prs.save(args.out)
    print(f"✔ Saved {args.out}")


if __name__ == "__main__":  # pragma: no cover
    main()