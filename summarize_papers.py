import argparse
import os
from pathlib import Path

from openai import OpenAI
from pypdf import PdfReader


def extract_text(pdf_path: Path) -> str:
    """Extract text from a PDF file."""
    text_parts = []
    try:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                page_text = ""
            text_parts.append(page_text)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Failed to read {pdf_path}: {exc}")
    return "\n".join(text_parts)


def summarize(text: str, client: OpenAI) -> str:
    """Call DeepSeek to summarize the paper."""
    prompt = (
        "请根据以下论文内容，提炼出：(1)针对的现象；(2)由此现象导致的问题；"
        "(3)论文提出的机制；(4)论文的最终结果。\n\n"
        f"\n{text}\n"
    )
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    return response.choices[0].message.content.strip()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Summarize PDFs using DeepSeek")
    parser.add_argument("path", type=Path, help="Directory containing PDF files")
    parser.add_argument("--api-key", dest="api_key", help="DeepSeek API key; if omitted, read from DEEPSEEK_API_KEY env var")
    parser.add_argument("--out", type=Path, default=Path("summaries"), help="Directory to save summaries")
    args = parser.parse_args(argv)

    api_key = args.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        parser.error("DeepSeek API key must be provided via --api-key or DEEPSEEK_API_KEY")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    args.out.mkdir(parents=True, exist_ok=True)

    pdf_paths = list(args.path.rglob("*.pdf"))
    if not pdf_paths:
        print("No PDF files found.")
        return

    for pdf_path in pdf_paths:
        print(f"Processing {pdf_path} ...")
        text = extract_text(pdf_path)
        summary = summarize(text, client)
        out_file = args.out / (pdf_path.stem + ".txt")
        out_file.write_text(summary, encoding="utf-8")
        print(f"Saved summary to {out_file}")


if __name__ == "__main__":
    main()