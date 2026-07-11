# bytebite 🔍🍪

> A pocket detective for mystery files. Sniffs magic bytes to identify unknown
> binaries, then hands you an **annotated hex peek** with the header fields
> labeled.

You know the feeling: a nameless `download (3)` or a random `.bin` shows up and
you have *no idea* what it is. `file` gives you a terse one-liner; a hex editor
gives you a wall of bytes with zero meaning. `bytebite` sits in the friendly
middle — it tells you **what** the file is, **why** it thinks so, and shows you
the header with the interesting parts *labeled*.

```
$ bytebite mystery.blob
🔍 PNG image  (category: image)   confidence: 94%
   matched magic \x89PNG\x0d\x0a\x1a\x0a at offset 0x00–0x07
   → Portable Network Graphics — lossless raster image.

$ bytebite peek mystery.blob
🔦 hex peek — mystery.blob   showing 29 byte(s)
   highlighting PNG image magic at 0x00–0x07; 9 header field(s) decoded
00000000  89 50 4e 47 0d 0a 1a 0a  00 00 00 0d 49 48 44 52  |.PNG........IHDR|
00000010  00 00 07 80 00 00 04 38  08 06 00 00 00           |.......8.....   |
          ^^^^^^^^^^^^^^^^^^^^^^^ PNG image magic
   decoded header fields:
       0x10–0x13  width       = 1920
       0x14–0x17  height      = 1080
            0x18  bit depth   = 8
            0x19  colour type = truecolour+alpha (RGBA) (6)

$ cat mystery.blob | bytebite -
🔍 PNG image  (category: image)   confidence: 94%
   matched magic \x89PNG\x0d\x0a\x1a\x0a at offset 0x00–0x07
   → Portable Network Graphics — lossless raster image.

$ bytebite mystery.blob --json
{"schema_version":1,"tool":"bytebite","source":"mystery.blob","identified":true,"match":{"name":"PNG image",...}}
```

## Why bytebite?

- **Explanation-first.** Not just *what*, but *which bytes prove it* and how
  confident it is.
- **Annotated, not raw.** Header fields are highlighted and labeled inline —
  see the meaning, not just the hex.
- **Tiny + local.** Pure Python standard library. No network, no telemetry, no
  accounts. Reads a file (or stdin) and gets out of your way.
- **Extensible by data.** Adding a new format is a signature entry, not a code
  rewrite.

## Status

🚧 Early days — see [`PLAN.md`](./PLAN.md) for the roadmap (M1–M6) and the open
[issues](../../issues). This repo is part of an automated tool-lab experiment
(topic: `auto-tool-lab`).

**Working now (M6):** `bytebite <file>` identifies a file by its magic bytes and
prints the format, category, confidence, and matched byte range. `bytebite peek
<file>` renders an annotated hex view of the header with the recognised
magic-byte range highlighted and labeled (colorized on a TTY, plain carets when
piped or `NO_COLOR` is set; `--bytes N` controls how much is shown). The registry
now covers ~20 everyday formats — PNG, JPEG, GIF, BMP, ICO, PDF, ZIP, GZIP, XZ,
BZIP2, ZSTD, 7-Zip, TAR (via its `ustar` header at offset 257), WAV, MP3,
SQLite, Parquet, ELF, PE, Java class and WebAssembly. Both commands also read
from **stdin** with `-`, so bytebite composes in pipelines
(`cat mystery.blob | bytebite -`). Tiny and empty inputs are handled without
crashing. `--json` gives a stable, versioned one-line JSON payload and `--quiet`
prints just the format name, both with predictable exit codes (`0` identified,
`1` unknown, `2` error) — see [Scripting](#scripting--json-output). **New in M6:**
`peek` now decodes and labels **individual header fields** — not just the magic
range — for **PNG** (IHDR: width/height/bit depth/colour type…), **ELF** (class,
endianness, OS ABI, type, machine — reading the right byte order per binary),
**ZIP** local headers (compression method, CRC-32, sizes…), and **WAV** fmt
chunks (audio format, channels, sample rate, bit depth…). The decoded values
appear in a legend under the dump (and in `peek --json` as a typed `fields`
list), and `bytebite --list-formats` lists every known format and marks which
have field-level detail. See [Field-level header annotation](#field-level-header-annotation).

**Also available:** `bytebite explain <format>` is a file-less pocket reference —
it prints a known format's magic bytes and documented header layout without
needing a sample file (e.g. `bytebite explain png`). See
[Explain a format](#explain-a-format).

## Install

```
# once published
pipx install bytebite
```

For now, clone and run from source:

```
git clone https://github.com/rwrife/bytebite
cd bytebite
python -m bytebite --help
```

## Usage

```
bytebite <file>          # identify a file (working now)
bytebite peek <file>     # annotated hex view of the header (working now)
bytebite peek <file> -n 32  # show the first 32 bytes (default: 64)
bytebite explain <format>   # print a format's magic + header layout (no file)
bytebite find --field width=1920 *.png  # search files by header field value
bytebite <file> --json   # machine-readable JSON line (working now)
bytebite <file> --quiet  # print only the format name, nothing if unknown
bytebite --list-formats  # list every known format + which have field detail
cat blob | bytebite -    # read from stdin (working now)
```

Examples:

```
$ bytebite mystery.blob
🔍 PNG image  (category: image)   confidence: 94%
   matched magic \x89PNG\x0d\x0a\x1a\x0a at offset 0x00–0x07
   → Portable Network Graphics — lossless raster image.

$ bytebite peek mystery.blob --bytes 16
🔦 hex peek — mystery.blob   showing 16 byte(s) (of ≥20 read)
   highlighting PNG image magic at 0x00–0x07
00000000  89 50 4e 47 0d 0a 1a 0a  00 00 00 0d 49 48 44 52  |.PNG........IHDR|
          ^^^^^^^^^^^^^^^^^^^^^^^ PNG image magic
```

Exit codes: `0` identified, `1` unidentified, `2` usage/I-O error.

## Field-level header annotation

For a handful of well-known formats, `bytebite peek` goes a step past the magic
range and decodes the **individual header fields**, so you can read a file's
actual dimensions, codec, or layout straight from the dump:

```
$ bytebite peek photo.png
🔦 hex peek — photo.png   showing 29 byte(s)
   highlighting PNG image magic at 0x00–0x07; 9 header field(s) decoded
00000000  89 50 4e 47 0d 0a 1a 0a  00 00 00 0d 49 48 44 52  |.PNG........IHDR|
00000010  00 00 07 80 00 00 04 38  08 06 00 00 00           |.......8.....   |
          ^^^^^^^^^^^^^^^^^^^^^^^ PNG image magic
   decoded header fields:
       0x08–0x0b  IHDR length = 13
       0x0c–0x0f  chunk type  = IHDR
       0x10–0x13  width       = 1920
       0x14–0x17  height      = 1080
            0x18  bit depth   = 8
            0x19  colour type = truecolour+alpha (RGBA) (6)
            0x1a  compression = deflate (0)
            0x1b  filter      = adaptive (0)
            0x1c  interlace   = none (0)
```

On a colour terminal the field spans light up inline in the dump; when piped or
under `NO_COLOR` the magic range is underlined with carets and every decoded
field is listed in the legend (so the output stays readable no matter how many
fields a format has).

Formats with field-level detail today:

- **PNG** — IHDR: width, height, bit depth, colour type, compression, filter,
  interlace.
- **ELF** — class (32/64-bit), data (endianness), version, OS ABI, type,
  machine. Byte order for `type`/`machine` is read per-binary from `EI_DATA`, so
  big- and little-endian binaries both decode correctly.
- **ZIP** local file header — version needed, flags, compression method, mod
  time/date, CRC-32, compressed/uncompressed sizes, name/extra lengths.
- **WAV** fmt chunk — audio format, channels, sample rate, byte rate, block
  align, bits per sample.

See everything the registry knows (and which formats carry field detail) with:

```
$ bytebite --list-formats
bytebite knows 22 formats (4 with field-level header detail):
  ...
  ELF executable       executable • fields
  ...
  PNG image            image      • fields

'• fields' formats decode individual header fields in `bytebite peek`.
```

`--list-formats --json` emits the same information as one machine-readable line
(`{"schema_version":1,"tool":"bytebite","formats":[{"name":...,"category":...,"fields":true},...]}`).

## Container awareness (ZIP → docx/jar/apk…)

Half the "why does it say ZIP?" confusion in the world comes from formats that
are *secretly just ZIP archives*: a `.docx` is a ZIP full of `word/*.xml`, a
`.jar` is a ZIP with `META-INF/MANIFEST.MF`, an `.apk` adds
`AndroidManifest.xml`, and an `.epub` leads with a `mimetype` member. When
bytebite identifies a real file as a ZIP, it peeks one level deeper at the
archive's member names and reports the *real* type:

```
$ bytebite report.docx
🔍 ZIP archive  (category: archive)   confidence: 75%
   matched magic PK\x03\x04 at offset 0x00–0x03
   → ZIP archive (local file header) — also the basis of jar/docx/apk.
   📦 ZIP container → looks like a .docx (Word document (OOXML))
      Office Open XML word processing document (ZIP of word/*.xml).
```

Recognised containers: **docx / xlsx / pptx** (OOXML), **jar**, **apk**,
**epub**, and **odt**. A plain ZIP with no tell-tale layout is reported as an
ordinary ZIP archive, unchanged.

Detection reads only the archive's central-directory listing (never the member
data), so it stays cheap and safe on hostile input. It needs a seekable file, so
piped/`stdin` sources are reported as a plain ZIP. In `--json` (and `peek
--json`) the real type rides along under `match.container`:

```json
"container": {"name": "Word document (OOXML)", "extension": "docx", "description": "..."}
```

for recognised containers, or `null` otherwise. (This bumped the JSON
`schema_version` to **`2`**; the field is additive, so v1 consumers that ignore
unknown keys keep working.)

## Fuzzy structured search (`find`)

The original Hacker News wish behind bytebite was *"an explorative hex editor
with fuzzy field search"* — point it at a pile of mystery binaries and ask which
ones match a header value. That's `bytebite find`:

```
$ bytebite find --field width=1920 *.png
hero.png: PNG image (width=1920)
banner.png: PNG image (width=1920)
```

It identifies each file, decodes its header fields with the same machinery as
`peek`, and keeps the files whose fields satisfy **every** `--field` predicate.

- **Match by value or label.** `--field method=deflate` and `--field method=8`
  both work — enum fields match on their human label *or* raw value.
- **Numeric comparisons.** `=` is exact; `>=`, `<=`, `>`, `<` compare numbers
  (`--field 'width>=1920'`, `--field 'sample rate=48000'`). Quote clauses with
  `>`/`<` so your shell doesn't redirect them.
- **Repeatable (AND).** `--field width=1920 --field height=1080` keeps only
  files that match both.
- **Field names are case-insensitive** and may contain spaces (`'sample rate'`).

Exit codes: `0` at least one match, `1` no files matched, `2` bad/empty query.
`--json` emits one stable line: `{ "action": "find", "query": [...], "count": N,
"matches": [ { "path", "format", "fields": [...] } ] }`.

```
$ bytebite find --field 'width>=1000' --field height=1080 --json photo.png
{"schema_version":2,"tool":"bytebite","action":"find","query":["width>=1000","height=1080"],"count":1,"matches":[{"path":"photo.png","format":"PNG image","fields":[{"name":"width","value":1920,"label":null},{"name":"height","value":1080,"label":null}]}]}
```

## Explain a format

Don't have a sample file but want to remember what a header looks like?
`bytebite explain <format>` prints the format's magic bytes and its documented
header layout straight from the registry — a pocket reference, no file required:

```
$ bytebite explain png
📖 PNG image  (category: image)
   Portable Network Graphics — lossless raster image.

Magic:
   \x89PNG\x0d\x0a\x1a\x0a   @ offset 0x00

Header fields:
   0x08–0x0b  4B  u32be  IHDR length  — chunk length (13)
   0x0c–0x0f  4B  ascii  chunk type   — always 'IHDR'
   0x10–0x13  4B  u32be  width        — pixels
   0x14–0x17  4B  u32be  height       — pixels
   0x18       1B  u8     bit depth
   0x19       1B  u8     colour type
   0x1a       1B  u8     compression
   0x1b       1B  u8     filter
   0x1c       1B  u8     interlace

Known values:
   colour type: 0=grayscale, 2=truecolour (RGB), 3=indexed, ...
   compression: 0=deflate
   ...
```

The format token is forgiving: `png`, `PNG`, `.png` and the full `PNG image`
all resolve, as do leading mnemonics for the rest (`elf`, `zip`, `wav`, `sqlite`
…). Formats that only have magic-byte identification (no decoded header) say so
instead of a field table. An ambiguous or unknown token exits `2` with a
"did you mean …?" hint. `--json` emits the same reference as one stable line for
tooling (building docs, shell completions, etc.):

```
$ bytebite explain wav --json
{"schema_version":1,"tool":"bytebite","format":{"name":"WAV audio","category":"audio","description":"...","signatures":[{"magic":"RIFF????????WAVE","offset":0,"masked":true}],"fields":[{"name":"RIFF","offset":0,"size":4,"type":"ascii","note":"container tag"}, ...]}}
```

> Unlike `peek` (a viewer that exits `0` even on unknown input), `explain`
> requires a *known* format name, so a bad name is a `2` (usage error).

## Scripting / JSON output

bytebite is built to be a good pipeline citizen.

**Exit codes** (stable, the contract for `bytebite <file>`):

| code | meaning |
| ---- | ------------------------------ |
| `0`  | file identified |
| `1`  | file read but not identified |
| `2`  | usage error / file I-O error |

> `bytebite peek` is a *viewer*: a successful render exits `0` even for an
> unknown blob. Use bare `bytebite <file>` (optionally `--quiet`/`--json`) when
> you want the exit code to gate on identification.

**`--quiet` (`-q`)** prints only the format name, or nothing when the file is
unknown — so you can branch on it directly:

```
if kind=$(bytebite mystery.blob --quiet); then
  echo "it's a $kind"
else
  echo "no idea what that is"   # exit 1, empty output
fi
```

**`--json`** emits exactly one compact JSON line (no trailing chatter, colour
never included) for both `identify` and `peek`, so `bytebite f --json | jq` and
line-oriented tools work as expected:

```
$ bytebite mystery.blob --json
{"schema_version":1,"tool":"bytebite","source":"mystery.blob","identified":true,"match":{"name":"PNG image","category":"image","confidence":0.94,"description":"Portable Network Graphics — lossless raster image.","offset":0,"end":8,"magic":"\\x89PNG\\x0d\\x0a\\x1a\\x0a"}}
```

### JSON schema

Every payload carries `schema_version` (currently **`2`**) so scripts can pin to
a known shape. `identify --json`:

```jsonc
{
  "schema_version": 2,
  "tool": "bytebite",
  "source": "mystery.blob",   // path, "<stdin>", or null
  "identified": true,
  "match": {                   // null when identified == false
    "name": "PNG image",
    "category": "image",
    "confidence": 0.94,        // float in (0, 1]
    "description": "Portable Network Graphics — lossless raster image.",
    "offset": 0,               // start of the matched magic range
    "end": 8,                  // exclusive end of the range
    "magic": "\\x89PNG\\x0d\\x0a\\x1a\\x0a",
    "container": null          // ZIP-based real type (docx/jar/apk…) or null
  }
}
```

`peek --json` is a superset — the same identification keys plus a `peek` object
with the dump metadata, labelled highlight spans, and (M6) a typed `fields` list
of the decoded header fields:

```jsonc
{
  ...identify keys...,
  "peek": {
    "bytes_shown": 29,         // bytes actually rendered (honours --bytes)
    "total_read": 29,          // bytes read from the source head
    "hex": "89504e47...",      // lowercase hex of the shown bytes
    "spans": [                 // labelled ranges (magic + fields; empty when unidentified)
      {"start": 0, "end": 8, "label": "PNG image magic", "hex": "89504e470d0a1a0a"},
      {"start": 16, "end": 20, "label": "width", "hex": "00000780"}
    ],
    "fields": [                // decoded header fields (empty if the format has no layout)
      {
        "name": "width",       // field label / JSON-friendly key
        "offset": 16, "end": 20, "size": 4,
        "type": "u32be",       // decoder: u8|u16be|u16le|u32be|u32le|ascii|hex|magic
        "value": 1920,         // decoded value
        "label": null,         // human label for enum fields (e.g. "deflate"), else null
        "hex": "00000780",
        "note": "pixels"       // optional short human note
      }
    ]
  }
}
```

## License

MIT
