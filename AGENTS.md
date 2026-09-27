# AGENTS.md

## What this is

One-page site that converts a file to Markdown using Microsoft MarkItDown:
Next.js UI + Python function, deployed as one Vercel project.

## Architecture

- `frontend/` — Next.js 16 (App Router, Turbopack) + React 19 + Tailwind v4, **pnpm**.
- `backend/` — FastAPI + MarkItDown, entrypoint `main:app`. Python pinned to 3.13.
- `vercel.json` — **Vercel Services**: `web` + `api` services, with top-level rewrites
  sending `/api/*` to Python and everything else to Next.

**The Python function is load-bearing.** MarkItDown is Python-only — its `packages/`
directory holds only `markitdown`, `markitdown-mcp`, `markitdown-ocr` and
`markitdown-sample-plugin`. There is no official browser build, so conversion cannot
happen client-side. Unofficial npm ports (`markitdown-js`, `markitdown-ts`) have partial
format coverage; swapping to one silently falsifies the core promise.

### Non-obvious wiring

- **The Python service receives the original request path.** Vercel does not strip the
  `/api` prefix, so the route is declared at `/api/convert` in `backend/main.py`. Declaring
  `/convert` yields a 404 in production while working locally — a nasty mismatch.
- **`frontend/next.config.ts` has a dev-only rewrite** proxying `/api/*` to
  `127.0.0.1:8000`, because `next dev` knows nothing about `vercel.json`. It is skipped
  when `NODE_ENV === "production"`, so it never competes with the real Vercel routing.
- **`uvicorn` is deliberately NOT in `requirements.txt`.** Vercel's runtime loads the ASGI
  `app` object directly. `uvicorn` is a local-only tool; adding it bloats the bundle.

## Commands

Frontend, from `frontend/`:

```
pnpm dev      # dev server
pnpm lint     # ESLint (flat config)
pnpm build    # production build; also typechecks and regenerates route types
```

Backend, from `backend/`:

```
.venv/bin/python -m uvicorn main:app --port 8000   # dev server
```

Full local stack needs **both** processes — start the backend first, then the frontend.
See `README.md` for first-time venv setup. `vercel dev` runs both together but rebuilds
Python from `requirements.txt` and is much slower to iterate on.

- **There is no test suite.** Do not add a test runner unless asked.
- **`next lint` does not exist in Next 16** — `package.json` maps `lint` to `eslint`
  directly. `npx next lint` fails with "Invalid project directory".
- Verify with `pnpm lint && pnpm build`, plus a real conversion through the running stack.
- Python venvs use `uv` (installed), mirroring Vercel.

### Typecheck gotcha

`.next/types` is gitignored, so `tsc --noEmit` fails on a fresh clone. Run `pnpm build`
once to generate those types first. Never "fix" this by hand-writing a props type.

## MarkItDown specifics

- Install `markitdown[pdf,docx,pptx,xlsx]`. **Do not pull `[all]`** — it drags in
  `azure-ai-documentintelligence`, `azure-identity`, `speechrecognition`, `pydub`, `xlrd`
  and `youtube-transcript-api`, none of which this site exposes.
- **`xls` is deliberately not installed, and `.xls` is refused up front.** Without the
  extra, `xlrd` is absent but `XlsConverter.accepts()` still matches `.xls`, so the request
  fails inside `convert()` with a missing-dependency error that reads like a corrupt file.
  `UNSUPPORTED_EXTENSIONS` in `main.py` rejects it with an honest 415 instead. Adding the
  extra means removing it from that set.
- **Construct `MarkItDown()` once at module scope.** Its `__init__` loads the magika ONNX
  model (~24 MB of onnxruntime); per-request construction would wreck cold start. The same
  module-scope block also strips the `ZipConverter` out of the instance — see "Archive
  handling" below for why.
- Pass `StreamInfo(extension=..., filename=...)` to `convert()`. Without it MarkItDown sees
  only an anonymous byte stream and format detection is far less reliable — an `.xlsx`
  with no name is just a ZIP. Note that this makes the declared extension *a* guess rather
  than *the* guess: magika can add a second one, which is why the archive guard cannot rely
  on the extension alone.
- Leave `enable_plugins` at its default `False`; never pass `--use-plugins`. This parses
  untrusted uploads and plugins are arbitrary third-party code.
- `defusedxml` is a base dependency and is what makes XML/HTML parsing safe. Do not remove.
- **Error types differ by cause.** `UnsupportedFormatException` is *not* what most failures
  raise — a bad archive raises `FileConversionException`. Catch broadly and map to a 4xx;
  an uncaught converter error becomes an opaque 500.
- **A missing optional dependency is not a bad file.** MarkItDown still matches a converter
  by extension even when that converter's extra was never installed, then fails inside
  `convert()`. `main.py` inspects `FileConversionException.attempts` and answers 415 for
  that case rather than the 422 used for genuinely malformed input.
- **MarkItDown falls back to plain text.** A `.rtf`, `.svg` or unrecognised extension does
  not error; `PlainTextConverter` returns the raw bytes as Markdown with a 200. Images are
  the opposite — the converter succeeds and returns an empty string. The frontend treats
  empty output as a failure, so this is handled, but do not assume a 200 means the
  conversion was meaningful. A *corrupt* PDF does raise (`PDFSyntaxError` →
  `FileConversionException` → 422); only images come back empty.
- `magika` is pinned `~=0.6.1` by markitdown. Do not force it to 1.x.

### Output post-processing in `main.py`

MarkItDown targets LLM pipelines, so some of what it emits is wrong for a rendered
preview. `_clean_markdown()` handles three cases, and the scoping matters:

- The PPTX converter writes `<!-- Slide number: N -->` before every slide and the DOCX and
  HTML converters map underline to a literal `<u>` tag. The preview renders Markdown
  **without** `rehype-raw` (deliberately — see Security), so raw HTML would be escaped and
  shown to the user as visible text. Both are rewritten away.
- Embedded images become `![alt](Picture1.jpg)` with no image data behind them, and DOCX
  images become a truncated `data:image/png;base64...` URI. Both are replaced with their
  alt text.
- JSON and XML come back as raw text on one line, so they are fenced as code. JSON is
  pretty-printed first; `.jsonl` is left alone because pretty-printing would merge its
  records.

**The HTML rewrites are scoped to `_HTML_DERIVED_EXTENSIONS` on purpose.** Every other
format is passed through close to verbatim, so a `<u>` typed into a `.csv` cell or a
`<!-- -->` in a `.md` file is the *user's own data* — rewriting it corrupts the document.
The `.csv` and `.xlsx` writers round-trip cell text through HTML, which un-escapes angle
brackets, so a cell containing `<u>literal</u>` really does arrive as a live-looking tag.
Do not widen this set without checking that the format's converter cannot emit literal
user text.

A real Word underline and the typed text `<u>x</u>` are byte-identical by the time
post-processing runs, so underline is dropped rather than guessed at. DESIGN.md has no
underline in its type system, so this is not a loss.

## Archive handling — read before touching the ZIP guard

`.docx`, `.pptx`, `.xlsx` and `.epub` are ZIP containers and begin with `PK\x03\x04`, so
they cannot be separated from a plain archive by magic bytes. Two layers guard this:

1. **Declared extension** — `BLOCKED_EXTENSIONS` in `backend/main.py` rejects archives by
   extension, deliberately not by magic bytes, since sniffing for the ZIP header would
   reject the entire core feature set.
2. **ZIP member list** — for the four container formats above, the archive is opened and
   its member list must contain the marker the format requires (`word/`, `ppt/`, `xl/`,
   `META-INF/container.xml`). A renamed archive has none of them.

**The extension check alone is NOT sufficient, and assuming it was is a real bug.** The
ZipConverter matches on `application/zip`, and `_get_stream_info_guesses()` emits a
*second* `.zip` guess whenever magika's detection disagrees with the declared extension —
`_convert()` then tries every guess against every converter. A ZIP named `report.docx`
was expanded recursively, nested archives included, despite the guard. This was verified
by execution, not assumed.

The third layer is that `main.py` **removes the ZipConverter from the instance entirely**,
so no archive is expanded even if a request gets past both checks.

If you change any of this, re-test a real `.docx`, `.xlsx` and `.pptx` end-to-end *and* a
renamed archive that must still be rejected.

## Limits

- **4 MB per file, enforced in both halves.** Vercel caps request *and* response bodies at
  4.5 MB (`413 FUNCTION_PAYLOAD_TOO_LARGE`), and converted Markdown can be about as large
  as its input. The browser gate is UX; `MAX_FILE_BYTES` in `backend/main.py` is the real
  one. Keep the two constants in sync.
- **Rate limit is best-effort.** `_hits` in `backend/main.py` is per-instance in-process
  state — Fluid compute may reuse or replace instances and run several concurrently, so it
  is not a global quota. A durable limit needs shared state (Upstash) or Vercel WAF.

## DESIGN.md is the source of truth — but its Tailwind block has 4 real bugs

Read `DESIGN.md` before any UI change. Its "Quick Start -> Tailwind v4" block must **not**
be copied literally; these fail silently rather than erroring. `frontend/src/app/globals.css`
documents each one at the top of the file:

| DESIGN.md says | What actually happens | Use instead |
|---|---|---|
| `--radius-full: 80px` | redefines `rounded-full` from a pill to 80px | `--radius-cards: 80px` |
| `--radius-full-2: 100px` | confusing name | `--radius-pills: 100px` |
| `--spacing-4: 4px` ... | Tailwind's `--spacing` is a 4px *multiplier*, so `p-4` becomes 4px not 16px | omit; use the native scale |
| `--page-max-width: 1200px` | not a Tailwind namespace; `max-w-page` resolves to nothing | `--container-page: 1200px` |

Line-height and tracking must be attached as `--text-*--line-height` /
`--text-*--letter-spacing` pairs. DESIGN.md's standalone `--leading-*` / `--tracking-*`
keys are not bundled into `text-*`, so the mandated display line-height of exactly `1.0`
would silently not apply.

**The odd padding values are correct.** `px-5.5 py-4.5` on buttons is 22px/18px once the
4px multiplier is applied — exactly DESIGN.md's button spec. Do not "round" them.

**T1 Sans is proprietary and not installable.** Inter loads via `next/font/google` as the
substitute DESIGN.md sanctions.

### Hard design rules (easy to violate)

- **Shadowless.** No `shadow-*` utilities, ever. Hierarchy is tonal (vellum -> white ->
  carbon -> onyx), not elevation.
- **Weights 300/400 only**, except 500 on inline `<strong>` and table headers.
  Headlines are weight 300 — never bold or semibold.
- **Monochrome.** No accent colors, gradients, or decorative hues.
- **`--color-pure-black` is for SVG fills only** — never text, backgrounds or borders.
- **Radii:** images/cards 80px, buttons/pills 100px, nothing below 8px.
- **Section labels** always take the 4px solid square prefix — not a dot or icon, and no
  emoji anywhere in labels or body copy.
- Section gap 48px, card padding 22px, page max-width 1200px.
- The hero is intentionally flat vellum. DESIGN.md's reference hero is full-bleed
  industrial photography, but it also forbids abstract graphics — with no licensed
  photograph available, a decorative stand-in would violate the system, so do not add one.

## Security

This app parses **untrusted arbitrary files** and renders Markdown derived from them.

- Never enable MarkItDown plugins on user input.
- Rendering stays on `react-markdown` + `remark-gfm`. **Do not add `rehype-raw`** — it
  would allow raw HTML through and open an XSS hole on a public page.
- Window-level `dragover`/`drop` are cancelled in `file-converter.tsx` so dropping a file
  does not make the browser navigate away.

### Next.js 16 gotchas

- **`next dev` writes its own `frontend/AGENTS.md`**, not this file. It appends a block
  delimited by `<!-- BEGIN:nextjs-agent-rules -->` / `<!-- END:nextjs-agent-rules -->`
  (see `node_modules/next/dist/server/lib/generate-agent-files.js`). It only ever edits the
  directory it runs in, so this root file is unaffected — but edit *around* those markers
  in `frontend/AGENTS.md` rather than deleting them.
- **Next 16 ships its own docs** at `frontend/node_modules/next/dist/docs/`. Its APIs and
  conventions differ from older training data — read the relevant guide before writing
  Next-specific code rather than relying on recall.
