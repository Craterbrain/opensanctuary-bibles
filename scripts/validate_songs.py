#!/usr/bin/env python3
"""Checks songs/public-domain-hymns.json against songs/catalog.json and the inclusion rule in SONGS.md.

    python3 scripts/validate_songs.py            # CI: exits non-zero on any problem
    python3 scripts/validate_songs.py --update   # rewrite songs/catalog.json after editing the hymns
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "songs" / "public-domain-hymns.json"
CATALOG = ROOT / "songs" / "catalog.json"
BANNED = ["here i am to worship", "god of grace and god of glory", "he is lord", "bless the lord, o my soul", "the virgin mary had a baby boy"]

raw = FILE.read_bytes()
songs = json.loads(raw)
catalog = {
    "format": 1,
    "repository": "Craterbrain/opensanctuary-bibles",
    "file": "songs/public-domain-hymns.json",
    "songs": len(songs),
    "bytes": len(raw),
    "sha256": hashlib.sha256(raw).hexdigest(),
    "license": "Public domain",
    "rule": "SONGS.md",
}
if "--update" in sys.argv:
    CATALOG.write_text(json.dumps(catalog, indent=1) + "\n", encoding="utf-8")
    print(f"updated catalog: {len(songs)} songs")
    sys.exit(0)

problems = []
if json.loads(CATALOG.read_text(encoding="utf-8")) != catalog:
    problems.append("songs/catalog.json does not match the file (run with --update)")
ids, keys = set(), set()
for s in songs:
    t = s.get("title", "")
    author = s.get("author", "").strip().lower()
    basis = s.get("basis", "")
    key = (t.strip().lower(), author)
    if s["id"] in ids or key in keys:
        problems.append(f"duplicate: {t}")
    ids.add(s["id"]); keys.add(key)
    if s.get("copyright") != "Public Domain" or s.get("ccli_number"):
        problems.append(f"{t}: must say Public Domain and carry no CCLI number")
    words = sum(len(sl["text"].split()) for sl in s["slides"])
    if words < 12:
        problems.append(f"{t}: almost no lyrics")
    unnamed = author in ("", "author unknown", "unknown", "custom", "media ministry")
    vague = any(w in ("anonymous", "traditional", "spiritual", "carol") for w in re.split(r"[^a-z]+", author))
    if (unnamed or vague) and len(basis) <= 10:
        problems.append(f"{t}: no named author and no stated basis")
    if "source" in s and not basis:
        problems.append(f"{t}: has a source but no basis")
    if "test" in t.lower() or t.lower() in BANNED:
        problems.append(f"{t}: must not be in the library")
    lyrics = " ".join(sl["text"] for sl in s["slides"]).lower()
    if any(m in lyrics for m in ("©", "ccli", "all rights reserved", "used by permission")):
        problems.append(f"{t}: rights notice in the lyrics")
if problems:
    print("\n".join(problems[:40]))
    sys.exit(f"{len(problems)} problem(s)")
print(f"ok: {len(songs)} hymns")
