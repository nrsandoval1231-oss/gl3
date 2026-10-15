"""Run with the existing private GridLens runtime; never writes the database."""
import argparse
import json
from pathlib import Path

from gridlens.intelligence.editorial import export_editorial
from gridlens.persistence.database import SessionLocal

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reviews', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
with SessionLocal() as session:
    feed = export_editorial(session, args.reviews)
# Exclusive creation avoids overwriting retained review evidence or an old export.
with args.output.open('x', encoding='utf-8') as output:
    json.dump(feed, output, indent=2)
    output.write('\n')
print(f"Exported {len(feed['items'])} candidates; {len(feed['rejected'])} rejections.")
