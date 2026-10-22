#!/usr/bin/env python3
"""Checks catalog.json against the files in bibles/. Run by CI; exits non-zero on any problem.

    python3 scripts/validate.py
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert import BOOK_NAMES, CANON, ROOT  # noqa: E402

problems = []
catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
bibles = catalog["bibles"]
canonical = [name for _, name in CANON]
known = set(BOOK_NAMES.values())

for key in ("id", "abbreviation"):
    values = [b[key] for b in bibles]
    for dup in {v for v in values if values.count(v) > 1}:
        problems.append(f"duplicate {key}: {dup}")
on_disk = {p.stem for p in (ROOT / "bibles").glob("*.json")}
if on_disk != {b["id"] for b in bibles}:
    problems.append(f"bibles/ and catalog.json disagree: {sorted(on_disk ^ {b['id'] for b in bibles})}")

for b in bibles:
    name = b["id"]
    path = ROOT / b["file"]
    if b["license"] != "Public domain" or "public domain" not in b["copyright"].lower():
        problems.append(f"{name}: not recorded as public domain")
    if not path.is_file():
        problems.append(f"{name}: {b['file']} is missing")
        continue
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != b["sha256"] or len(raw) != b["bytes"]:
        problems.append(f"{name}: file does not match catalog.json (rerun scripts/convert.py)")
    data = json.loads(raw)
    books = list(data)
    if [x for x in books if x not in known]:
        problems.append(f"{name}: unknown books {[x for x in books if x not in known]}")
    if books[: len(canonical)] != canonical:
        problems.append(f"{name}: the 66 canonical books must come first, in order")
    verses = 0
    for book, chapters in data.items():
        # (Some deuterocanonical books are fragments: the KJV's "Rest of Esther" is chapters 10-16.)
        if not chapters or (book in canonical and "1" not in chapters):
            problems.append(f"{name}: {book} has no chapter 1")
        for ch, vs in chapters.items():
            if not ch.isdigit() or int(ch) < 1 or not vs:
                problems.append(f"{name}: {book} bad chapter {ch!r}")
            for n, text in vs.items():
                verses += 1
                if not n.isdigit() or int(n) < 1 or not text.strip() or text != text.strip() or "\\" in text:
                    problems.append(f"{name}: {book} {ch}:{n} is malformed")
                    break
    if verses != b["verses"]:
        problems.append(f"{name}: {verses} verses, catalog says {b['verses']}")

if problems:
    print("\n".join(problems[:40]))
    sys.exit(f"{len(problems)} problem(s)")
print(f"ok: {len(bibles)} translations, {sum(b['verses'] for b in bibles):,} verses")
