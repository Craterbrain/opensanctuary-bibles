# OpenSanctuary Bibles

Public-domain Bible translations, converted into one simple JSON format, for [OpenSanctuary](https://github.com/Craterbrain/opensanctuary) and anything else that wants scripture text nobody can take away.

**64 translations in 30 languages** (see [BIBLES.md](BIBLES.md)), including the KJV, WEB, ASV, BSB, YLT, Darby, Douay-Rheims, Reina-Valera 1909, Louis Segond 1910, Luther 1912, the Synodal Bible and the Clementine Vulgate. Every text is public domain; each one's source and licence statement is in [NOTICE.md](NOTICE.md).

**221 public-domain English hymns** with the evidence for each one (see [SONGS.md](SONGS.md)), in `songs/public-domain-hymns.json`. OpenSanctuary downloads them from its first-run wizard or Import dialog.

## Using it in OpenSanctuary

Turn on the **Online Bibles** plugin (Settings → Plugins), open the **Scriptures** tab and pick *Online Bibles*: these translations are listed first, marked as from this repository. Install one and it is in your library for good; nothing is fetched while you run a service.

## Files

| File | What |
|---|---|
| `catalog.json` | Every translation: id, abbreviation, name, language, counts, size, `sha256`, licence, source |
| `bibles/<id>.json` | One translation |
| `BIBLES.md` / `NOTICE.md` | Human-readable list; per-translation sources and licence statements |
| `scripts/convert.py` | Rebuilds everything from ebible.org (`scripts/selection.json` says which) |
| `songs/public-domain-hymns.json` / `songs/catalog.json` | The hymn library (OpenSanctuary song format) and its count, size and `sha256` |
| `scripts/validate_songs.py` | Checks the hymns against the rule in SONGS.md (CI runs it) |
| `scripts/validate.py` | Checks the catalog against the files (CI runs it) |

A Bible file is nested objects, book → chapter → verse → text:

```json
{ "Genesis": { "1": { "1": "In the beginning, God created the heavens and the earth.", "2": "..." } }, "Exodus": { "...": {} } }
```

- Books are in canonical order: the 66 books first (`Genesis` … `Revelation`, with `Psalms` and `Song of Solomon`), then any deuterocanonical books the translation carries (`Tobit`, `Sirach`, `1 Maccabees`, ...).
- Verse text is plain: footnotes, cross-references, headings, Strong's numbers and other markup are removed, and paragraph or poetry breaks become spaces. A verse a translation omits (Matthew 17:21 in some) is absent. A bridged verse (`\v 1-2` in the source) is stored under its first number.
- The one-chapter books and short books follow the translation's own chapter numbering.

Raw URL pattern: `https://raw.githubusercontent.com/Craterbrain/opensanctuary-bibles/main/bibles/<id>.json`. Pin a commit instead of `main` if you want it to never change.

## Licensing

The texts are public domain, as stated by [ebible.org](https://ebible.org)'s translation catalogue, which is where they come from; the converter refuses anything that catalogue doesn't mark as public domain *and* redistributable. A few notes, since "public domain" depends on where you are:

- **King James Version:** public domain everywhere except the United Kingdom, where the Crown holds a perpetual letters-patent right to print it.
- **World English Bible and Berean/Majority Standard Bibles:** dedicated to the public domain by their publishers. "World English Bible" and "WEB" are names their publisher asks you not to use for a *modified* text; these files change only formatting.
- Older translations (Luther 1912, Reina-Valera 1909, Louis Segond 1910, ...) are public domain by age in most countries.

If you believe something here is not free to redistribute, please open an issue and it will be removed promptly. The conversion scripts are MIT-licensed ([LICENSE](LICENSE)); that licence does not apply to the Bible texts, which have no copyright holder to license them.

## Rebuilding

```sh
python3 scripts/convert.py            # downloads from ebible.org (cached in sources/, not committed) and rebuilds
python3 scripts/validate.py
```

To add a translation: find its id in [ebible.org's translations.csv](https://ebible.org/Scriptures/translations.csv), add it to `scripts/selection.json` with an abbreviation, language and English name (abbreviations must be unique), and rerun the converter.
