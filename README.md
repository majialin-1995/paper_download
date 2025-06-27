# paper_download

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