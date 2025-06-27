import argparse
from typing import List
import os
import sys

try:
    import openreview
except ImportError:
    openreview = None

import requests

CONFERENCE_MAPPING = {
    'ICLR': 'ICLR.cc/{year}/Conference',
    'ICML': 'MLResearch.org/ICML/{year}',
    'NIPS': 'NeurIPS.cc/{year}/Conference',
    'AAAI': 'AAAI.org/{year}/Conference'
}

def search_papers(conference: str, year: int, keyword: str):
    if openreview is None:
        raise RuntimeError('openreview package is required to search papers')
    group = CONFERENCE_MAPPING.get(conference)
    if not group:
        raise ValueError(f'Unsupported conference: {conference}')
    group_id = group.format(year=year)
    client = openreview.api.OpenReviewClient(baseurl='https://api2.openreview.net')
    notes = client.get_notes(invitation=f'{group_id}/-/Blind_Submission', term=keyword)
    return notes

def format_reference(note) -> str:
    """Return a simple GB7714-2015 style reference string."""
    title = note.content.get('title', 'Untitled')
    authors = note.content.get('authors', [])
    authors_str = '; '.join(authors)
    venue = note.content.get('venue', '') or note.content.get('conference', '')
    year = note.content.get('year', '')
    return f"{authors_str}. {title}[C]//{venue}, {year}."

def download_pdf(note, directory: str) -> str:
    pdf_url = note.content.get('pdf')
    if not pdf_url:
        return ''
    os.makedirs(directory, exist_ok=True)
    response = requests.get(pdf_url)
    filename = os.path.join(directory, f"{note.id}.pdf")
    with open(filename, 'wb') as f:
        f.write(response.content)
    return filename

def main(argv: List[str]):
    parser = argparse.ArgumentParser(description='Search and download papers from openreview.')
    parser.add_argument('--conference', required=True, help='Conference name: ICLR, ICML, NIPS, AAAI')
    parser.add_argument('--year', type=int, required=True, help='Year of the conference')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--output', default='pdfs', help='Directory to save PDFs')
    parser.add_argument('--reference', default='references.txt', help='Output reference list file')
    args = parser.parse_args(argv)

    try:
        notes = search_papers(args.conference, args.year, args.keyword)
    except Exception as e:
        sys.stderr.write(str(e) + '\n')
        return 1

    refs = []
    for note in notes:
        ref = format_reference(note)
        refs.append(ref)
        path = download_pdf(note, args.output)
        print(f'Downloaded {path}')
    with open(args.reference, 'w', encoding='utf-8') as f:
        for r in refs:
            f.write(r + '\n')
    print(f'Written references to {args.reference}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))