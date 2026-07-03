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
🔍 PNG image  (category: image)   confidence: 99%
   matched magic \x89PNG\r\n\x1a\n at offset 0x00
   → Portable Network Graphics — lossless raster image

$ bytebite peek mystery.blob
00000000  [89 50 4E 47 0D 0A 1A 0A] 00 00 00 0D 49 48 44 52  |.PNG........IHDR|
          └── magic: PNG signature ──┘        └ IHDR chunk ┘
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

**Working now (M2):** `bytebite <file>` identifies a file by its magic bytes and
prints the format, category, confidence, and matched byte range. It knows the
common seed formats: PNG, JPEG, GIF, PDF, ZIP, GZIP, ELF and PE. The annotated
hex `peek` (M3) and `--json` output (M5) are next.

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
bytebite peek <file>     # annotated hex view of the header (planned, M3)
bytebite <file> --json   # machine-readable output (planned, M5)
cat blob | bytebite -    # read from stdin (planned, M4)
```

Example:

```
$ bytebite mystery.blob
🔍 PNG image  (category: image)   confidence: 94%
   matched magic \x89PNG\x0d\x0a\x1a\x0a at offset 0x00–0x07
   → Portable Network Graphics — lossless raster image.
```

Exit codes: `0` identified, `1` unidentified, `2` usage/I-O error.

## License

MIT
