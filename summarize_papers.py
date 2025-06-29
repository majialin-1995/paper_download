#!/usr/bin/env python3
"""
 pdf_summary_with_tqdm.py (v2.1 – 2025-06-28)
 -------------------------------------------------
 已正式发表 PDF → 提取正文 → DeepSeek-chat 摘要（JSON）→ tqdm 进度条

 关键特性
 =========
 • 精准 / 近似两级 token 计数，强制 ≤ 55k   (TOKEN_BUDGET)  
 • 若仍超限，summarize() 自动递减 10 % 重试
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from openai import OpenAI
from pypdf import PdfReader
from tqdm.auto import tqdm

# ══════════════════════════════════════════════════════════
# 全局常量
# ══════════════════════════════════════════════════════════
TOKEN_BUDGET = 55_000          # 留足提示开销，DeepSeek 上限 65 536
MIN_RETRY_BUDGET = 1_000       # 少于此 token 仍报错则放弃

# ══════════════════════════════════════════════════════════
# token 计数 & 截断
# ══════════════════════════════════════════════════════════
try:
    import tiktoken  # type: ignore
    _ENCODING = tiktoken.encoding_for_model("gpt-4o")  # DeepSeek 兼容 cl100k
    def _token_count(text: str) -> int:
        return len(_ENCODING.encode(text))

    def clip_to_budget(text: str, budget: int = TOKEN_BUDGET) -> str:
        ids = _ENCODING.encode(text)
        return _ENCODING.decode(ids[:budget])

except ModuleNotFoundError:
    # ── 简易近似：CJK 1 token，其余字符 4≈1 token
    _CJK_RE = re.compile(r"[\u4e00-\u9fff]")

    def _token_count(text: str) -> int:
        cjk = len(_CJK_RE.findall(text))
        other = len(text) - cjk
        return cjk + other // 4 + 1

    def clip_to_budget(text: str, budget: int = TOKEN_BUDGET) -> str:
        if _token_count(text) <= budget:
            return text
        # 线性削减
        ratio = budget / _token_count(text)
        cut_len = int(len(text) * ratio)
        return text[:cut_len]

# ══════════════════════════════════════════════════════════
# 正则与工具
# ══════════════════════════════════════════════════════════
_FENCE_RE = re.compile(r"^```[a-z]*\n|\n```$", re.I | re.M)
_JSON_RE  = re.compile(r"\{.*?\}", re.S)

def extract_text(pdf_path: Path) -> str:
    text_parts: List[str] = []
    try:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                text_parts.append("")
    except Exception as exc:
        print(f"[warn] 无法读取 {pdf_path}: {exc}")
    return "\n".join(text_parts)

def _extract_json(blob: str) -> Dict[str, Any] | None:
    cleaned = _FENCE_RE.sub("", blob.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = _JSON_RE.search(cleaned)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None

# ══════════════════════════════════════════════════════════
# DeepSeek 调用
# ══════════════════════════════════════════════════════════
_PROMPT_HEADER = (
    "请根据以下论文内容，用中文（不要是英文！！！）总结要点，且缩写需给出中文全称（英文全称，英文缩写）：\n"
    "  (1) 涉及的现象；\n  (2) 由该现象产生的问题（问题与机制要一一对应，用（1）（2）（3）…标号）；\n"
    "  (3) 论文提出的机制（问题与机制要一一对应，用（1）（2）（3）…标号）；\n"
    "  (4) 论文实验结果（需说明具体数据集 / 环境名称；以及数据集 / 环境对应的性能具体数值）。\n\n"
    "⚠️ 仅输出 JSON，字段必须且只能为 phenomenon / problem / mechanism / result。\n\n"
)

def summarize(text: str, client: OpenAI) -> Dict[str, Any]:
    budget = TOKEN_BUDGET

    while True:
        clipped = clip_to_budget(text, budget)
        prompt = _PROMPT_HEADER + clipped + "\n"
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant"},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                stream=False,
            )
            content = resp.choices[0].message.content
            data = _extract_json(content) or {"raw": content}
            return data

        except Exception as exc:
            msg = str(exc)
            if "maximum context length" in msg and budget > MIN_RETRY_BUDGET:
                budget = int(budget * 0.9)  # 再减 10 %
                continue
            raise  # 其它错误直接抛出

# ══════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════
def main(argv: List[str] | None = None) -> None:
    p = argparse.ArgumentParser("批量总结 PDF (≤55k token)")
    p.add_argument("path", type=Path, help="包含 PDF 的目录")
    p.add_argument("--api-key", dest="api_key",
                   help="DeepSeek API key；若省略读取 DEEPSEEK_API_KEY 环境变量")
    p.add_argument("--out", type=Path, default=None,
                   help="JSON 输出目录，默认 <path>/summaries")
    args = p.parse_args(argv)

    api_key = args.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        p.error("必须提供 DeepSeek API key (--api-key 或环境变量 )")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    if args.out is None:
        args.out = args.path.parent / "summaries"

    pdfs = sorted(args.path.rglob("*.pdf"))
    if not pdfs:
        print("⚠️ 未找到 PDF")
        return
    args.out.mkdir(parents=True, exist_ok=True)

    for pdf in tqdm(pdfs, desc="Processing PDFs", unit="file"):
        raw = extract_text(pdf)
        if not raw.strip():
            tqdm.write(f"[skip] {pdf.name} 提取文本为空")
            continue

        try:
            summary = summarize(raw, client)
        except Exception as e:
            tqdm.write(f"[error] {pdf.name}: {e}")
            continue

        out_path = args.out / f"{pdf.stem}.json"
        out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        tqdm.write(f"✅ {pdf.stem}.json 已保存")

    print(f"✔ 摘要已保存至 {args.out}")

if __name__ == "__main__":  # pragma: no cover
    main()
