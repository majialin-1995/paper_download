#!/usr/bin/env python3
"""
 pdf_summary_with_tqdm.py (v3.3 – 2025-06-28)
 -------------------------------------------------
 已正式发表 PDF → 提取正文 → DeepSeek-chat 摘要（JSON）→ tqdm 进度条

 结构要求
 =========
 • phenomenon:  现象列表，每个元素是一条独立“现象”（字符串）
 • problem:     问题列表（不要求与现象一一对应）
 • mechanism:   机制 / 方法列表（不要求与现象一一对应）
 • result:      实验结果列表：
                 - 每个元素是一条完整的中文句子
                 - 必须包含：使用的环境 / 数据集 / 任务名称 + 对应的性能数值
                 - 由 LLM 自行控制内容，我们只做类型规范（不再拆分字符串）
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from openai import OpenAI
from pypdf import PdfReader
from tqdm.auto import tqdm
from pydantic import BaseModel, Field

# ==========================================================
# Token 预算
# ==========================================================
TOKEN_BUDGET = 55_000
MIN_RETRY_BUDGET = 1_000

# ==========================================================
# Pydantic 结构 & 轻量类型规范（不拆内容）
# ==========================================================

class Summary(BaseModel):
    phenomenon: List[str] = Field(default_factory=list)
    problem:    List[str] = Field(default_factory=list)
    mechanism:  List[str] = Field(default_factory=list)
    result:     List[str] = Field(default_factory=list)


def to_string_list(x: Any) -> List[str]:
    """
    强制将输入转换为 List[str]，但完全不做“句子拆分”：
    - 字符串  → 单元素列表
    - 列表    → 每个元素转 str 并 strip
    - 其它类型 → 单元素字符串列表
    """
    if x is None:
        return []

    if isinstance(x, str):
        s = x.strip()
        return [s] if s else []

    if isinstance(x, list):
        out: List[str] = []
        for item in x:
            s = str(item).strip()
            if s:
                out.append(s)
        return out

    # 其它类型
    s = str(x).strip()
    return [s] if s else []


def normalize_summary(raw: Dict[str, Any]) -> Summary:
    """
    确保最终一定是合法 Summary(List[str])，但不修改 LLM 输出内容结构。
    """
    data = {
        "phenomenon": to_string_list(raw.get("phenomenon")),
        "problem":    to_string_list(raw.get("problem")),
        "mechanism":  to_string_list(raw.get("mechanism")),
        "result":     to_string_list(raw.get("result")),
    }
    return Summary.model_validate(data)

# ==========================================================
# Token 计数
# ==========================================================

try:
    import tiktoken
    _ENC = tiktoken.encoding_for_model("gpt-4o")

    def _token_count(text: str) -> int:
        return len(_ENC.encode(text))

    def clip_to_budget(text: str, budget: int = TOKEN_BUDGET) -> str:
        ids = _ENC.encode(text)
        return _ENC.decode(ids[:budget])

except ModuleNotFoundError:
    _CJK = re.compile(r"[\u4e00-\u9fff]")

    def _token_count(text: str) -> int:
        cjk = len(_CJK.findall(text))
        other = len(text) - cjk
        return cjk + other // 4 + 1

    def clip_to_budget(text: str, budget: int = TOKEN_BUDGET) -> str:
        if _token_count(text) <= budget:
            return text
        ratio = budget / _token_count(text)
        return text[: int(len(text) * ratio)]

# ==========================================================
# JSON 解析
# ==========================================================
_FENCE = re.compile(r"^```[a-z]*\n|\n```$", re.I | re.M)
_JSON  = re.compile(r"\{.*?\}", re.S)


def _extract_json(blob: str) -> Dict[str, Any] | None:
    """
    尝试从 LLM 返回文本中提取 JSON：
    - 去掉 ```json fenced block
    - 直接 json.loads
    - 若失败则用正则抓第一个 { ... } 片段再解析
    """
    cleaned = _FENCE.sub("", blob.strip())
    try:
        return json.loads(cleaned)
    except Exception:
        m = _JSON.search(cleaned)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None

# ==========================================================
# Prompt（v3.3：不再假设我们会拆分，要求 LLM 自己控制每项）
# ==========================================================

_PROMPT_HEADER = """
请根据以下论文内容，用中文输出一个 JSON 对象，字段必须且只能为：
phenomenon / problem / mechanism / result。

【字段含义】
- phenomenon:  论文中讨论的关键“现象”，一条独立、完整的中文描述。
- problem:     针对现象或相关背景引出的2~3个最关键的“问题 / 挑战”，为问题列表。
- mechanism:   论文提出的主要“机制 / 方法 / 模型设计”，为机制列表（与问题列表一一对应）。
- result:      实验结果与性能表现，每个元素必须：
    1) 明确写出使用的环境 / 数据集 / 任务名称（例如：YCB、CartPole、Pong、某真实机器人平台等）；
    2) 给出具体数值（如准确率、成功率、奖励、AUC 等，可以在一句话中包含多个数值对比）；
    3) 是一条完整的自然中文句子，而不是“在 环境A 中：性能 = XXX”这样的 key=value 形式。

【格式要求（非常重要）】
1. 你必须输出一个 JSON 对象，形如：
   {
     "phenomenon": ["...", "..."],
     "problem": ["...", "..."],
     "mechanism": ["...", "..."],
     "result": ["...", "..."]
   }

2. 每个字段的值必须是字符串数组 (List[str])。
   - 每个数组元素是一条独立的完整句子（或一个完整条目）；
   - 严禁将多条内容挤在同一个字符串中用“；”、“、”、“。”等分隔，
     你应该为每一条内容新建一个数组元素。

3. 只输出 JSON，不要输出任何解释性文字。
4. 用到缩写的地方需要按照中文全称（英文全称，英文缩写）的形式
下面是论文内容：
"""

# ==========================================================
# DeepSeek 调用 + 结构规范
# ==========================================================

def summarize(text: str, client: OpenAI) -> Summary:
    """
    调用 DeepSeek-chat 完成一次摘要：
    - 自动控制 token 上限：超过就 0.9 × budget 递减重试
    - 保证返回值为 Summary（Pydantic 校验通过）
    """
    budget = TOKEN_BUDGET

    while True:
        clipped = clip_to_budget(text, budget)
        prompt = _PROMPT_HEADER + clipped

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
            content = resp.choices[0].message.content or ""
            raw_json = _extract_json(content) or {}

            # —— 不再拆分字符串，只统一成 List[str] 并做 schema 校验
            return normalize_summary(raw_json)

        except Exception as exc:
            msg = str(exc)
            if "maximum context length" in msg and budget > MIN_RETRY_BUDGET:
                budget = int(budget * 0.9)
                continue
            raise

# ==========================================================
# PDF 文本提取
# ==========================================================

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

# ==========================================================
# 主流程
# ==========================================================

def main(argv: List[str] | None = None) -> None:
    p = argparse.ArgumentParser("批量总结 PDF（结构化 JSON 输出）")
    p.add_argument("path", type=Path, help="包含 PDF 的目录")
    p.add_argument(
        "--api-key",
        dest="api_key",
        help="DeepSeek API key；若省略则读取 DEEPSEEK_API_KEY 环境变量",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON 输出目录，默认 <path>/summaries",
    )
    args = p.parse_args(argv)

    api_key = args.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        p.error("必须提供 DeepSeek API key (--api-key 或环境变量 DEEPSEEK_API_KEY)")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    out_dir = args.out or (args.path.parent / "summaries")
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(args.path.rglob("*.pdf"))
    if not pdfs:
        print("⚠ 未找到 PDF")
        return

    for pdf in tqdm(pdfs, desc="Processing PDFs", unit="file"):
        text = extract_text(pdf)
        if not text.strip():
            tqdm.write(f"[skip] {pdf.name} 文本为空")
            continue

        try:
            summary = summarize(text, client)
        except Exception as e:
            tqdm.write(f"[error] {pdf.name}: {e}")
            continue

        out_path = out_dir / f"{pdf.stem}.json"
        out_path.write_text(
            json.dumps(summary.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tqdm.write(f"✔ {pdf.stem}.json 已保存")

    print(f"所有摘要已保存到：{out_dir}")


if __name__ == "__main__":  # pragma: no cover
    main()
