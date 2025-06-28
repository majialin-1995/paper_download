#!/usr/bin/env python3
"""根据 summaries 目录生成演示文稿"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable

from pptx import Presentation  # type: ignore
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

try:
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None  # type: ignore

# 检测中文字符
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

def is_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def translate(text: str, client: OpenAI | None) -> str:
    return text


def ensure_chinese(obj: Any, client: OpenAI | None) -> Any:
    if isinstance(obj, str):
        return translate(obj, client)
    if isinstance(obj, Iterable):
        return [ensure_chinese(x, client) for x in obj]
    if isinstance(obj, dict):
        return {k: ensure_chinese(v, client) for k, v in obj.items()}
    return obj


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser("根据 summaries 生成 PPT")
    p.add_argument("summaries", type=Path, help="包含 JSON 摘要的目录")
    p.add_argument("--template", type=Path, default=Path("template.pptx"),
                   help="PPT 模板 (default: template.pptx)")
    p.add_argument("--out", type=Path, default=Path("slides.pptx"),
                   help="输出文件名")
    p.add_argument("--api-key", dest="api_key",
                   help="DeepSeek API key，用于翻译非中文内容")
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



def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    api_key = args.api_key or os.getenv("DEEPSEEK_API_KEY")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com") if api_key else None

    prs = Presentation(str(args.template))

    for idx, json_file in enumerate(sorted(args.summaries.glob("*.json")), 1):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        data = ensure_chinese(data, client)
        add_slide(prs, json_file.stem, data, idx)
        
    prs.save(args.out)
    print(f"✔ Saved {args.out}")


if __name__ == "__main__":  # pragma: no cover
    main()