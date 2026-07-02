# bytebite 🔍🍪

> A pocket detective for mystery files.

## 1. Pitch

`bytebite` is a tiny, fast CLI that answers the two questions you actually have
when a nameless blob lands on your disk: **"What *is* this?"** and **"What's in
its header?"** It fingerprints unknown binaries by their magic bytes and
structural tells, then serves up an **annotated hex peek** where the recognized
header fields are labeled and colorized inline — so you can *see* the PNG IHDR,
the ZIP local-file header, or the ELF entry point without cracking open a
1,000-page spec or a full reverse-engineering suite.

## 2. Trend inspiration

- **Ask HN: "What developer tool do you wish existed in 2026?"**
  <https://news.ycombinator.com/item?id=46345827> — a top comment explicitly
  asks for *"an 'explorative' hex editor where you can do 'fuzzy' searches, e.g.,
  searching for a header with specific values for certain fields."* Another whole
  sub-thread is people wanting to *understand* opaque data faster (function graphs,
  structured search) rather than staring at raw bytes.
- **Windows Central — "4 tools for Windows 11 that stood out during Build 2026"**
  <https://www.windowscentral.com/microsoft/windows-11/4-tools-for-windows-11-that-stood-out-to-me-during-build-2026>
  — the platform trend is toward small, sharp, developer-quality-of-life
  utilities (Coreutils, Intelligent Terminal) shipping as first-class citizens.
- **Neowin / WindowsForum "Top utilities of 2026" roundups** — the recurring
  theme is *local-first, privacy-respecting, single-purpose* tools that do one
  annoying job well. Identifying a mystery file is exactly that job.

The gap: the "what is this file + explain its header" need is real and repeated,
but the existing answers are either too small (`file` just prints one line) or
too big (a full hex editor / RE platform). Nobody sits comfortably in the middle
with a *friendly, annotated* answer.

## 3. Why it's different

There's plenty of prior art in adjacent lanes — this deliberately doesn't step
on any of them:

- **`file` / libmagic** — prints a one-line guess and stops. `bytebite` tells you
  *why* it thinks so (which bytes matched), how confident it is, and then shows
  you the labeled header. `file` never annotates the hex.
- **`hexyl` / `xxd` / `hexdump`** — gorgeous/plain raw dumps with zero semantic
  understanding. They don't know a PNG from a paperweight. `bytebite` overlays
  *meaning* on top of the bytes.
- **ImHex / 010 Editor / Kaitai Struct** — heavyweight, GUI-first (or full DSL)
  reverse-engineering platforms. Powerful, but you don't reach for them to answer
  "what's this 4KB blob in my Downloads?" `bytebite` is a 2-second terminal ask,
  not a project you open.
- **`binwalk`** — firmware-carving and embedded-file extraction, security-focused.
  `bytebite` is about *identifying + explaining one file's header*, not recursively
  carving archives out of a firmware image.

The fresh angle: **explanation-first, human-friendly file identification.** Magic
bytes + a labeled header + a confidence score + "here's the byte range that
proves it," in one glanceable terminal view.

## 4. MVP scope (v0.1)

The smallest genuinely useful thing:

- `bytebite <file>` — identify the file and print:
  - detected format name + category (image / archive / executable / document / …)
  - confidence score + the exact matched magic-byte offset/range
  - a one-line human description of the format
- A built-in **signature registry** covering ~20 everyday formats (PNG, JPEG,
  GIF, PDF, ZIP, GZIP, ELF, PE/EXE, WAV, MP3, SQLite, Parquet, Class, WASM, …).
- `bytebite peek <file>` — annotated hex view of the first N bytes with the
  recognized **magic-byte range highlighted** and labeled.
- `--json` output for scripting/piping.
- Reads from **stdin** too (`cat blob | bytebite -`) so it composes in pipelines.
- Zero network calls. Local-only. No telemetry.

## 5. Tech stack

Boring, fast, cross-platform:

- **Python 3.11+** with **only the standard library** for the core (argparse,
  struct, sys). A blob-identifier should install in one step and run anywhere;
  no compile step, no native deps.
- **Signatures as data** — formats live in a plain `signatures.py`/JSON table
  (magic bytes, offset, mask, description, optional header layout), so adding a
  format is a data edit, not a code change.
- Optional dependency-free **ANSI color** (auto-disabled when not a TTY / when
  `NO_COLOR` is set). No color library needed.
- **pytest** for tests, packaged via **pyproject.toml** so `pipx install bytebite`
  gives you the `bytebite` command.

Rationale: pure-stdlib Python keeps the barrier to *contributing a new signature*
near zero, which is the whole extensibility story. Speed is fine — we only read
the first few KB of a file.

## 6. Architecture

Small, obvious modules:

- `bytebite/signatures.py` — the signature registry: a list of `Signature`
  records (name, category, magic bytes, offset, mask, description, optional
  `fields` layout for the annotated header).
- `bytebite/identify.py` — reads the file head, matches signatures, scores
  confidence, returns the best match(es).
- `bytebite/peek.py` — renders the annotated hex view (offset gutter, hex,
  ASCII, colorized/labeled field spans).
- `bytebite/render.py` — output formatting (human text, `--json`), TTY/color
  detection.
- `bytebite/cli.py` — argparse entry point wiring it all together.
- `tests/` — golden fixtures: tiny sample headers per format + expected output.

Data flow: `cli → identify (reads head) → render` for ID; `cli → identify →
peek → render` for the hex view.

## 7. Milestones

1. **M1 — Scaffold + hello-world.** Repo layout, `pyproject.toml`, `bytebite`
   console entry point that prints version + "no file given" help. `pytest`
   green in CI.
2. **M2 — Core identification engine.** `Signature` model + `identify.py` matching
   the first ~8 formats (PNG, JPEG, GIF, PDF, ZIP, GZIP, ELF, PE). `bytebite <file>`
   prints name + category + confidence + matched offset.
3. **M3 — Annotated hex peek.** `bytebite peek <file>` renders offset/hex/ASCII
   with the magic-byte range highlighted and labeled. TTY color + `NO_COLOR`.
4. **M4 — Registry to ~20 formats + stdin.** Expand signatures (WAV, MP3, SQLite,
   Parquet, WASM, Class, BMP, TAR, 7z, XZ, ICO…), support `bytebite -` from stdin,
   handle ambiguous/multi-match gracefully.
5. **M5 — `--json` + scripting polish.** Structured output, stable exit codes
   (0 = identified, 1 = unknown, 2 = error), `--quiet`, and piping ergonomics.
6. **M6 — Field-level header annotation.** For a handful of formats (PNG IHDR,
   ELF header, ZIP local header, WAV fmt chunk), decode and label individual
   header fields in `peek`, not just the magic range. Docs + `--list-formats`.

## 8. Backlog / future features (v0.2+)

1. **`bytebite explain <format>`** — print the header layout spec for a known
   format even without a file (a pocket reference).
2. **Container awareness** — note "this ZIP is actually a .docx/.jar/.apk" by
   peeking inside for tell-tale members.
3. **Fuzzy structured search** (the original HN ask): `bytebite find --field
   width=1920 *.bin` across a directory.
4. **Confidence via multiple signals** — combine magic bytes + trailer bytes +
   size heuristics for a better score.
5. **Custom signature files** — `~/.config/bytebite/signatures.d/*.json` so users
   drop in private/proprietary formats.
6. **`--diff`** — compare two files' identified structure side by side.
7. **Entropy strip** — a tiny per-region entropy bar to spot compressed/encrypted
   sections at a glance.
8. **Extract-header** — dump just the parsed header as JSON for tooling.
9. **Shell completions** + a `bytebite doctor` self-check.
10. **Kaitai / libmagic import** — optionally ingest existing signature DBs.
11. **Watch mode** — `bytebite watch ~/Downloads` announces the type of each new
    file as it lands.
12. **Web playground** — drag-a-file, see the annotated peek (static, client-side
    only).

## 9. Out of scope

Deliberately **not** building:

- A full interactive hex *editor* (no writing/patching bytes). Read-only, always.
- A firmware/archive **carver** — we identify and explain one file; we don't
  recursively extract embedded files (that's binwalk's job).
- A reverse-engineering **IDE** or scripting DSL (that's ImHex / Kaitai).
- **Malware analysis / sandboxing** — we never execute the file, and we make no
  safety claims about it.
- **Cloud, accounts, telemetry, or network calls** of any kind. Local-first,
  full stop.
- Deep, exhaustive parsing of *every* field of *every* format — we annotate the
  interesting header bits, not the entire binary.
