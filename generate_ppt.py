#!/usr/bin/env python3
"""根据 summaries 目录生成演示文稿（占位符替换版）

使用说明
--------
python generate_ppt.py summaries/ --template template.pptx --out slides.pptx

PPT 模板内应包含形如 {{title}}, {{reference}}, {{Pages}}, {{totalpages}},
{{problems}}, {{methods}}, {{results}} 的占位符。
"""

from __future__ import annotations
import argparse
import json
import re
import copy
from pathlib import Path
from typing import Any, Dict, List

try:
    from pptx import Presentation
    from pptx.util import Pt
except Exception:
    Presentation = None

PLACEHOLDER_FIELDS = {
    "{{title}}",
    "{{reference}}",
    "{{Pages}}",
    "{{problems}}", "{{methods}}", "{{results}}"
}

def find_reference(title: str, refs: List[str]) -> str:
    norm = re.sub(r"[^\w\s]", "", title).lower()
    for line in refs:
        if norm in re.sub(r"[^\w\s]", "", line).lower():
            return line
    return ""

def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser("根据 summaries 生成 PPT（占位符版）")
    p.add_argument("summaries", type=Path, help="包含 JSON 摘要的目录")
    p.add_argument("--template", type=Path, default=Path("template.pptx"), help="PPT 模板")
    p.add_argument("--out", type=Path, default=Path("slides.pptx"), help="输出文件名")
    p.add_argument("--refs", type=Path, default=Path("papers/references_ieee.txt"), help="参考文献文本")
    p.add_argument("--print-info", action="store_true", help="仅打印摘要信息，不生成 PPT")
    return p.parse_args(argv)

def duplicate_slide(prs, slide):
    new_slide = prs.slides.add_slide(slide.slide_layout)
    for shp in slide.shapes:
        el = shp.element
        new_el = copy.deepcopy(el)
        new_slide.shapes._spTree.insert_element_before(new_el, 'p:extLst')
    return new_slide

def list_to_text(lst: list[str] | None) -> str:
    return "\n".join(str(x) for x in (lst or []))

def result_to_text(result) -> str:
    try:
        if result is None:
            return ""
        if isinstance(result, dict):
            # 获取实验环境信息，字段名称可能有所不同
            env = (
                result.get("datasets_environments")
                or result.get("datasets")
                or result.get("dataset_environment")
            )
            if isinstance(env, list):
                env_text = "、".join(env)
            else:
                env_text = str(env) if env else ""

            perf = result.get("performance")
            if isinstance(perf, list):
                perf_text = " ".join(str(x) for x in perf)
            else:
                perf_text = str(perf) if perf is not None else ""

            parts = []
            if env_text:
                parts.append(f"实验中使用了{env_text}环境")
            if perf_text:
                parts.append(f"\n结果：{perf_text}")  # ← 改为换行
            return "".join(parts)

        return str(result)
    except Exception:
        return str(result)



def fill_placeholders(slide, data: dict[str, Any], title: str, reference: str,
                      page: int, total: int, section: str, idx: int) -> None:
    mapping = {
        "{{No.}}": str(idx),
        "{{title}}": title,
        "{{reference}}": reference,
        "{{Pages}}": str(page)+" / "+str(total),
    }
    if section == "intro":
        mapping["{{problems}}"] = "针对"+str(data.get("phenomenon"))+ "：\n" + list_to_text(data.get("problem"))
        mapping["{{methods}}"] = list_to_text(data.get("mechanism"))
    elif section == "conclusion":
        mapping["{{results}}"] = result_to_text(data.get("result"))

    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        tf = shape.text_frame
        for paragraph in tf.paragraphs:
            for run in paragraph.runs:
                txt = run.text
                for ph, value in mapping.items():
                    if ph in txt:
                        txt = txt.replace(ph, value)
                run.text = txt

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
            print(f"{i}. {title}\n{'-'*len(title)}")
            if ref:
                print(ref)
            print(json.dumps(data, ensure_ascii=False, indent=2), "\n")
        return

    if Presentation is None:
        raise SystemExit("请先: pip install python-pptx")

    prs = Presentation(str(args.template))

    base_intro, base_conclusion, base_thankyou = None, None, None
    for s in prs.slides:
        text = "\n".join(sh.text for sh in s.shapes if sh.has_text_frame)
        if "{{title}}" in text:
            base_title = s
        elif "{{problems}}" in text and "{{methods}}" in text:
            base_intro = s
        elif "{{results}}" in text:
            base_conclusion = s

    if not all([base_title, base_intro, base_conclusion]):
        raise SystemExit("❌ 模板缺失三页中的一页: title/intro/conclusion")

    ref_lines = args.refs.read_text(encoding="utf-8").splitlines() if args.refs.is_file() else []
    total = 125

    for idx, jf in enumerate(json_files, 1):
        data = json.loads(jf.read_text(encoding="utf-8"))
        title = jf.stem.split("_", 1)[1] if "_" in jf.stem else jf.stem
        reference = find_reference(title, ref_lines)

        slide1 = duplicate_slide(prs, base_title)
        fill_placeholders(slide1, data, title, reference, 3*idx-2+5, total, section="intro", idx=idx)

        slide2 = duplicate_slide(prs, base_intro)
        fill_placeholders(slide2, data, title, reference, 3*idx-1+5, total, section="intro", idx=idx)

        slide3 = duplicate_slide(prs, base_conclusion)
        fill_placeholders(slide3, data, title, reference, 3*idx+5, total, section="conclusion", idx=idx)

    prs.save(args.out)
    print(f"✔ 已保存: {args.out}")

    # 额外生成 No. + Reference 的 txt 列表
    ref_list_txt = []
    for idx, jf in enumerate(json_files, 1):
        title = jf.stem.split("_", 1)[1] if "_" in jf.stem else jf.stem
        reference = find_reference(title, ref_lines)
        ref_list_txt.append(f"[{idx}]. {reference}")

    ref_output_path = args.out.with_name("references_list.txt")
    ref_output_path.write_text("\n\n".join(ref_list_txt), encoding="utf-8")
    print(f"✔ 已额外保存参考文献列表: {ref_output_path}")

if __name__ == "__main__":
    main()
