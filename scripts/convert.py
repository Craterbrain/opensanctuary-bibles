#!/usr/bin/env python3
"""Rebuilds this repository's Bible files from ebible.org's USFM downloads.

    python3 scripts/convert.py                 # every translation in scripts/selection.json
    python3 scripts/convert.py engwebp eng-asv # just these
    python3 scripts/convert.py --refresh       # re-download the sources first

For each translation it downloads <id>_usfm.zip from ebible.org (cached under sources/, which git
ignores), turns the USFM into plain verse text, writes bibles/<id>.json, then rewrites
catalog.json and BIBLES.md from everything in bibles/.

Which translations are included is decided by scripts/selection.json, which lists only
translations ebible.org's own catalogue (translations.csv) marks public domain and
redistributable; the converter re-checks that column on every run and refuses anything else.

Output format -- what OpenSanctuary's Online Bibles plugin reads (it is also what "GitHub Bible
repository" imports use):

    { "Genesis": { "1": { "1": "In the beginning, God created ...", "2": "..." } }, ... }

Books are in canonical order (the 66-book Protestant canon, then any deuterocanonical books the
translation carries). Footnotes, cross-references, headings, Strong's numbers and other markup are
dropped; paragraph and poetry line breaks become spaces. A bridged verse ("\\v 1-2") is stored
under its first number. Verses with no text (verses a translation omits) are not stored.
"""
import csv
import hashlib
import io
import json
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
BIBLES = ROOT / "bibles"
EBIBLE = "https://ebible.org/Scriptures"
USER_AGENT = "opensanctuary-bibles/1 (+https://github.com/Craterbrain/opensanctuary-bibles)"

# USFM book id -> the book name OpenSanctuary uses (the plugin's BOOKS list, then the
# deuterocanon). Order here is output order.
CANON = [
    ("GEN", "Genesis"), ("EXO", "Exodus"), ("LEV", "Leviticus"), ("NUM", "Numbers"), ("DEU", "Deuteronomy"),
    ("JOS", "Joshua"), ("JDG", "Judges"), ("RUT", "Ruth"), ("1SA", "1 Samuel"), ("2SA", "2 Samuel"),
    ("1KI", "1 Kings"), ("2KI", "2 Kings"), ("1CH", "1 Chronicles"), ("2CH", "2 Chronicles"), ("EZR", "Ezra"),
    ("NEH", "Nehemiah"), ("EST", "Esther"), ("JOB", "Job"), ("PSA", "Psalms"), ("PRO", "Proverbs"),
    ("ECC", "Ecclesiastes"), ("SNG", "Song of Solomon"), ("ISA", "Isaiah"), ("JER", "Jeremiah"), ("LAM", "Lamentations"),
    ("EZK", "Ezekiel"), ("DAN", "Daniel"), ("HOS", "Hosea"), ("JOL", "Joel"), ("AMO", "Amos"),
    ("OBA", "Obadiah"), ("JON", "Jonah"), ("MIC", "Micah"), ("NAM", "Nahum"), ("HAB", "Habakkuk"),
    ("ZEP", "Zephaniah"), ("HAG", "Haggai"), ("ZEC", "Zechariah"), ("MAL", "Malachi"),
    ("MAT", "Matthew"), ("MRK", "Mark"), ("LUK", "Luke"), ("JHN", "John"), ("ACT", "Acts"),
    ("ROM", "Romans"), ("1CO", "1 Corinthians"), ("2CO", "2 Corinthians"), ("GAL", "Galatians"), ("EPH", "Ephesians"),
    ("PHP", "Philippians"), ("COL", "Colossians"), ("1TH", "1 Thessalonians"), ("2TH", "2 Thessalonians"),
    ("1TI", "1 Timothy"), ("2TI", "2 Timothy"), ("TIT", "Titus"), ("PHM", "Philemon"), ("HEB", "Hebrews"),
    ("JAS", "James"), ("1PE", "1 Peter"), ("2PE", "2 Peter"), ("1JN", "1 John"), ("2JN", "2 John"),
    ("3JN", "3 John"), ("JUD", "Jude"), ("REV", "Revelation"),
]
DEUTERO = [
    ("TOB", "Tobit"), ("JDT", "Judith"), ("ESG", "Esther (Greek)"), ("WIS", "Wisdom of Solomon"), ("SIR", "Sirach"),
    ("BAR", "Baruch"), ("LJE", "Letter of Jeremiah"), ("S3Y", "Prayer of Azariah"), ("SUS", "Susanna"),
    ("BEL", "Bel and the Dragon"), ("1MA", "1 Maccabees"), ("2MA", "2 Maccabees"), ("3MA", "3 Maccabees"),
    ("4MA", "4 Maccabees"), ("1ES", "1 Esdras"), ("2ES", "2 Esdras"), ("MAN", "Prayer of Manasseh"),
    ("PS2", "Psalm 151"), ("DAG", "Additions to Daniel"), ("ODA", "Odes"), ("PSS", "Psalms of Solomon"),
]
BOOK_NAMES = dict(CANON + DEUTERO)
ORDER = [c for c, _ in CANON + DEUTERO]
PROTESTANT = {c for c, _ in CANON}

# Paragraph / poetry / list markers: the rest of the line is verse text.
TEXT_MARKERS = re.compile(r"^(p|m|mi|nb|pc|pr|ph\d?|pi\d?|q\d?|qm\d?|qr|qc|qa|li\d?|lim\d?|lh|lf|b|cls|tr|tc\d?|tcr\d?|th\d?|thr\d?)$")
# Headings, titles, notes and the like: the whole line is dropped.
SKIP_MARKERS = re.compile(
    r"^(id|ide|usfm|sts|rem|h\d?|toc\d|mt\d?|mte\d?|imt\d?|is\d?|ip\w*|ipi\d?|im\w*|iq\d?|ili\d?|iot|io\d?|iex|imte\d?|ib|"
    r"ie|s\d?|ms\d?|mr|r|sr|d|sp|cl|cd|cp|ca|va|vp|restore|periph|k\d?|lit|esb|esbe|cat)$")

FOOTNOTE = re.compile(r"\\(f|fe|x|ef|ex)\s.*?\\\1\*", re.S)
FIGURE = re.compile(r"\\fig\s.*?\\fig\*", re.S)
ATTR_SPAN = re.compile(r"\\\+?(w|wg|wh|wa|rb|jmp|xt|ztext)\s+([^|\\]*)(?:\|[^\\]*)?\\\+?\1\*")
MILESTONE = re.compile(r"\\[a-z]+-[se]\b[^\\]*\\\*")
ANY_MARKER = re.compile(r"\\\+?[a-z]+\d?\*?")
NUMBER = re.compile(r"(\d+)([a-z]?)(?:\s*[-\u2013,]\s*(\d+)[a-z]?)?\s*(.*)", re.S)


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def catalogue(refresh: bool = False) -> dict:
    """ebible.org's own translation list (languages, titles, copyright, redistributable flag, counts)."""
    SOURCES.mkdir(exist_ok=True)
    path = SOURCES / "translations.csv"
    if refresh or not path.exists():
        path.write_bytes(http_get(f"{EBIBLE}/translations.csv"))
    rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")))
    return {r["translationId"]: r for r in rows}


def source_zip(tid: str, refresh: bool) -> bytes:
    path = SOURCES / f"{tid}_usfm.zip"
    if refresh or not path.exists():
        print(f"  downloading {tid}_usfm.zip", flush=True)
        path.write_bytes(http_get(f"{EBIBLE}/{tid}_usfm.zip"))
        time.sleep(1.5)  # one translation at a time, not in a burst
    return path.read_bytes()


def clean(text: str) -> str:
    text = ATTR_SPAN.sub(r"\2", text)
    text = ANY_MARKER.sub("", text)
    text = text.replace("~", " ").replace("//", " ").replace("\u00b6", " ")  # ~ no-break space, // line break, pilcrow
    text = re.sub(r"\s+", " ", text).strip()
    # A bare versification note a translator put in front of the verse ("[32:1]", "[14]", and the
    # Hebrew file's reversed "]73-63["): not part of the text.
    return re.sub(r"^(?:\[\d+(?:[:.]\d+)?(?:\s*[-\u2013]\s*\d+)?\]|\]\d+(?:[-:]\d+)?\[)\s*", "", text)


def parse_book(usfm: str):
    """-> (book code, {chapter: {verse: text}}), or (None, {}) for a file without verses."""
    usfm = usfm.lstrip("\ufeff")
    usfm = FOOTNOTE.sub("", usfm)
    usfm = FIGURE.sub("", usfm)
    usfm = MILESTONE.sub("", usfm)
    code = None
    chapters: dict = {}
    chapter = verse = None
    for raw in usfm.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"\\([a-z0-9]+)\*?(?:\s+(.*))?$", line)
        if not m:
            # a continuation line: more text for the verse in progress
            if chapter is not None and verse is not None:
                chapters[chapter][verse] += " " + line
            continue
        marker, rest = m.group(1), (m.group(2) or "")
        if marker == "id":
            code = rest.split()[0].upper() if rest.split() else None
        elif marker == "c":
            n = re.match(r"\d+", rest)
            chapter, verse = (int(n.group()), None) if n else (None, None)
            if chapter is not None:
                chapters.setdefault(chapter, {})
        elif marker == "v" and chapter is not None:
            n = NUMBER.match(rest)
            if not n:
                continue
            num, letter, text = int(n.group(1)), n.group(2), n.group(4)
            if letter and verse == num:  # "3b" continues verse 3
                chapters[chapter][verse] += " " + text
            else:
                verse = num
                chapters[chapter][verse] = chapters[chapter].get(verse, "") + (" " if verse in chapters[chapter] else "") + text
        elif TEXT_MARKERS.match(marker):
            if chapter is not None and verse is not None and rest:
                chapters[chapter][verse] += " " + rest
        elif SKIP_MARKERS.match(marker):
            continue
        else:
            # an inline character style that starts the line (\w, \nd, \add ...): text, with markers stripped later
            if chapter is not None and verse is not None:
                chapters[chapter][verse] += " " + line
    out = {}
    for ch in sorted(chapters):
        verses = {v: clean(t) for v, t in sorted(chapters[ch].items())}
        # An omitted verse is a bare "[]" (or nothing): not stored.
        verses = {str(v): t for v, t in verses.items() if re.search(r"\w", t)}
        if verses:
            out[str(ch)] = verses
    return code, out


def convert(tid: str, row: dict, refresh: bool) -> dict:
    zf = zipfile.ZipFile(io.BytesIO(source_zip(tid, refresh)))
    books = {}
    for name in zf.namelist():
        if not name.lower().endswith((".usfm", ".sfm")):
            continue
        code, chapters = parse_book(zf.read(name).decode("utf-8", errors="replace"))
        if code in BOOK_NAMES and chapters:
            books[code] = chapters
    bible = {BOOK_NAMES[c]: books[c] for c in ORDER if c in books}
    problems = []
    if not PROTESTANT <= set(books):
        problems.append("missing books: " + ", ".join(sorted(PROTESTANT - set(books))))
    def count(codes):
        return sum(len(v) for c in codes if c in books for v in books[c].values())
    verses = count(books)
    # ebible.org's own totals: the 66 canonical books, and (separately) the deuterocanon.
    for label, got, declared in (
        ("canonical", count(PROTESTANT), int(row["OTverses"] or 0) + int(row["NTverses"] or 0)),
        ("deuterocanonical", count(set(books) - PROTESTANT), int(row["DCverses"] or 0)),
    ):
        if declared and abs(got - declared) > declared * 0.03:
            problems.append(f"{got} {label} verses, ebible.org says {declared}")
    for book, chapters in bible.items():
        for ch, vs in chapters.items():
            for v, text in vs.items():
                if "\\" in text or re.search(r"\|[a-z-]+=\"", text):
                    problems.append(f"leftover markup in {book} {ch}:{v}")
                    break
    if problems:
        raise SystemExit(f"{tid}: " + "; ".join(problems[:5]))
    text = json.dumps(bible, ensure_ascii=False, separators=(",", ":")) + "\n"
    (BIBLES / f"{tid}.json").write_text(text, encoding="utf-8")
    return {
        "books": len(bible),
        "deuterocanon": sum(1 for c in books if c not in PROTESTANT),
        "chapters": sum(len(b) for b in bible.values()),
        "verses": verses,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "bytes": len(text.encode("utf-8")),
        "source_sha256": hashlib.sha256((SOURCES / f"{tid}_usfm.zip").read_bytes()).hexdigest(),
    }


def main(argv):
    refresh = "--refresh" in argv
    wanted = [a for a in argv if not a.startswith("--")]
    sel = json.loads((ROOT / "scripts/selection.json").read_text(encoding="utf-8"))
    cat = catalogue(refresh)
    BIBLES.mkdir(exist_ok=True)
    meta_path = ROOT / "scripts/built.json"
    built = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    for entry in sel["bibles"]:
        tid = entry["id"]
        if wanted and tid not in wanted:
            continue
        row = cat.get(tid)
        if not row:
            raise SystemExit(f"{tid}: not in ebible.org's translations.csv")
        if "public domain" not in row["Copyright"].lower() or row["Redistributable"] != "True":
            raise SystemExit(f"{tid}: ebible.org no longer lists it as a redistributable public-domain text ({row['Copyright']!r})")
        print(f"{tid}: {row['title']}", flush=True)
        built[tid] = convert(tid, row, refresh)
        built[tid]["update_date"] = row["UpdateDate"][:10]
    meta_path.write_text(json.dumps(built, indent=1, sort_keys=True) + "\n")
    write_catalog(sel, cat, built)


def write_catalog(sel: dict, cat: dict, built: dict):
    bibles = []
    for entry in sel["bibles"]:
        tid = entry["id"]
        if tid not in built or not (BIBLES / f"{tid}.json").exists():
            continue
        row, b = cat[tid], built[tid]
        bibles.append({
            "id": tid,
            "abbreviation": entry["abbreviation"],
            "name": entry.get("name") or row["title"].strip(),
            "language": entry["language"],
            "language_code": row["languageCode"],
            "file": f"bibles/{tid}.json",
            "books": b["books"],
            "deuterocanon": b["deuterocanon"],
            "chapters": b["chapters"],
            "verses": b["verses"],
            "bytes": b["bytes"],
            "sha256": b["sha256"],
            "license": "Public domain",
            "copyright": row["Copyright"].strip(),
            "source": f"{EBIBLE}/{tid}_usfm.zip",
            "source_sha256": b["source_sha256"],
            "source_updated": b["update_date"],
            "publication_url": row["publicationURL"].strip(),
        })
    (ROOT / "catalog.json").write_text(json.dumps({"format": 1, "repository": "Craterbrain/opensanctuary-bibles", "bibles": bibles},
                                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    lines = ["# Included translations", "", "| Abbr. | Translation | Language | Books | Verses | Size |", "|---|---|---|---|---|---|"]
    for b in sorted(bibles, key=lambda b: (b["language"] != "English", b["language"], b["name"])):
        extra = f" (+{b['deuterocanon']} deuterocanonical)" if b["deuterocanon"] else ""
        lines.append(f"| {b['abbreviation']} | {b['name']} | {b['language']} | {b['books']}{extra} | {b['verses']:,} | {b['bytes'] / 1e6:.1f} MB |")
    (ROOT / "BIBLES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    notice = [
        "# Sources and attribution", "",
        "Every text here is in the public domain. Each was converted from ebible.org's USFM download of the same name;",
        "the licence statement is ebible.org's own, copied from its translation catalogue. Only the formatting was changed",
        "(see README.md): the wording is as published.", "",
    ]
    for b in sorted(bibles, key=lambda b: (b["language"] != "English", b["language"], b["name"])):
        notice += [f"## {b['name']} ({b['abbreviation']}) -- {b['language']}", "",
                   f"- Licence: {b['license']} (ebible.org: \"{b['copyright']}\")",
                   f"- Source: {b['source']} (updated {b['source_updated']})"]
        if b["publication_url"]:
            notice.append(f"- Publication page: {b['publication_url']}")
        notice += [f"- File: `{b['file']}`", ""]
    (ROOT / "NOTICE.md").write_text("\n".join(notice), encoding="utf-8")
    print(f"catalog.json: {len(bibles)} translations")


if __name__ == "__main__":
    main(sys.argv[1:])
