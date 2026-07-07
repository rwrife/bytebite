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
🔦 hex peek — mystery.blob   showing 20 byte(s)
   highlighting PNG image magic at 0x00–0x07
00000000  89 50 4e 47 0d 0a 1a 0a  00 00 00 0d 49 48 44 52  |.PNG........IHDR|
00000010  00 00 00 10                                       |....            |
          ^^^^^^^^^^^^^^^^^^^^^^^ PNG image magic

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

**Working now (M5):** `bytebite <file>` identifies a file by its magic bytes and
prints the format, category, confidence, and matched byte range. `bytebite peek
<file>` renders an annotated hex view of the header with the recognised
magic-byte range highlighted and labeled (colorized on a TTY, plain carets when
piped or `NO_COLOR` is set; `--bytes N` controls how much is shown). The registry
now covers ~20 everyday formats — PNG, JPEG, GIF, BMP, ICO, PDF, ZIP, GZIP, XZ,
BZIP2, ZSTD, 7-Zip, TAR (via its `ustar` header at offset 257), WAV, MP3,
SQLite, Parquet, ELF, PE, Java class and WebAssembly. Both commands also read
from **stdin** with `-`, so bytebite composes in pipelines
(`cat mystery.blob | bytebite -`). Tiny and empty inputs are handled without
crashing. **New in M5:** `--json` gives a stable, versioned one-line JSON payload
and `--quiet` prints just the format name, both with predictable exit codes
(`0` identified, `1` unknown, `2` error) — see [Scripting](#scripting--json-output).
Field-level header annotation (M6) is next.

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
bytebite <file> --json   # machine-readable JSON line (working now)
bytebite <file> --quiet  # print only the format name, nothing if unknown
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

Every payload carries `schema_version` (currently **`1`**) so scripts can pin to
a known shape. `identify --json`:

```jsonc
{
  "schema_version": 1,
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
    "magic": "\\x89PNG\\x0d\\x0a\\x1a\\x0a"
  }
}
```

`peek --json` is a superset — the same identification keys plus a `peek` object
with the dump metadata and labelled highlight spans:

```jsonc
{
  ...identify keys...,
  "peek": {
    "bytes_shown": 12,         // bytes actually rendered (honours --bytes)
    "total_read": 12,          // bytes read from the source head
    "hex": "89504e470d0a1a0a0000000d",  // lowercase hex of the shown bytes
    "spans": [                 // labelled ranges (empty when unidentified)
      {"start": 0, "end": 8, "label": "PNG image magic", "hex": "89504e470d0a1a0a"}
    ]
  }
}
```

## License

MIT
