# markitdown

One-page web app that converts a file to Markdown using
[Microsoft MarkItDown](https://github.com/microsoft/markitdown).

Drop in a PDF, Word document, PowerPoint, Excel workbook, HTML, CSV, JSON or XML
file and get Markdown back, rendered in the page and ready to copy or download.

See "Output quality" under Limits for what each format actually produces —
MarkItDown is designed for LLM pipelines, so PDF in particular is text
extraction only.

## Stack

| Part | Technology |
|------|------------|
| Frontend | Next.js 16 (App Router, Turbopack), React 19, Tailwind v4, pnpm |
| Backend | FastAPI + MarkItDown, deployed as a Python Vercel Function |
| Hosting | Vercel, with both halves in one project via Vercel Services |

MarkItDown is a Python library with no official browser build, so a server-side
function is required — the conversion cannot happen in the browser.

## Layout

```
vercel.json      # services + rewrites: /api/* -> Python, everything else -> Next
DESIGN.md        # the visual system (see "Design" below)
frontend/        # Next.js app
backend/         # FastAPI app (entrypoint main:app)
```

## Local development

The app needs both halves running. Vercel routes `/api/*` to the Python service
in production, but `next dev` knows nothing about `vercel.json`, so
`frontend/next.config.ts` proxies `/api/*` to `http://127.0.0.1:8000` during
development. Start the backend first.

**Backend** (first run downloads onnxruntime and pandas, so allow a few minutes):

```bash
cd backend
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python uvicorn   # local server only
.venv/bin/python -m uvicorn main:app --port 8000
```

**Frontend** (in a second terminal):

```bash
cd frontend
pnpm install
pnpm dev
```

Then open http://localhost:3000.

Alternatively `vercel dev` runs both services together with production-like
routing, but it builds the Python service from `requirements.txt` and is much
slower to iterate on than the two-terminal setup above.

## Commands

Frontend, from `frontend/`:

```bash
pnpm dev      # dev server
pnpm lint     # ESLint (flat config)
pnpm build    # production build; also typechecks and regenerates route types
```

There is no test suite. Verify changes with `pnpm lint && pnpm build`, plus a
real conversion through the running stack.

### Typecheck gotcha

`.next/types` is gitignored, so `tsc --noEmit` fails on a fresh clone. Run
`pnpm build` once to generate those types first.

## Limits

- **4 MB per file.** Vercel caps both request and response bodies at 4.5 MB
  (`413 FUNCTION_PAYLOAD_TOO_LARGE`), and converted Markdown can be roughly as
  large as its input. The browser checks the size before uploading; the backend
  enforces the same cap independently, because the browser check is trivially
  bypassable.
- **Archives are rejected** (`.zip`, `.tar`, `.gz`, `.7z`, and similar).
  MarkItDown ships a ZIP converter that recursively expands archives, which is a
  zip-bomb and CPU-exhaustion vector on a public endpoint. That converter is
  also removed from the instance in `backend/main.py`, so nothing expands an
  archive even if a request gets past the guard.
- **Rate limit:** 20 conversions per minute per IP. This is best-effort,
  in-process state — see the caveat in `backend/main.py`.

`.docx`, `.pptx`, `.xlsx` and `.epub` are themselves ZIP containers and begin
with the bytes `PK\x03\x04`. They are allowed through, but not on the strength
of their extension alone: the ZIP member list is checked for the marker the
format requires (`word/`, `ppt/`, `xl/`, `META-INF/container.xml`). A renamed
archive has none of those and is rejected.

### Output quality

MarkItDown is built for LLM pipelines, not for high-fidelity human-readable
conversion, and its own README says so. What that means here:

- **PDF is text extraction only.** No headings, lists or bold are reconstructed,
  and a scanned or image-only PDF yields nothing. There is no OCR, because that
  needs the `markitdown-ocr` plugin and enabling plugins on untrusted uploads is
  not acceptable.
- **JSON and XML have no Markdown equivalent**, so they are returned as fenced
  code rather than being silently mangled into prose.
- **Images are not supported.** The image converter needs `exiftool` plus an LLM
  client to produce anything, neither of which this deployment has.
- `.xls`, `.doc`, `.rtf`, `.odt` and `.svg` are refused up front with a 415.
  `.xls` would need the `xls` extra; the others have no converter and would fall
  through to plain-text passthrough.

`backend/main.py` post-processes converter output to remove the HTML that
MarkItDown emits on purpose (PPTX slide comments, DOCX `<u>` underline tags) and
to replace image links that cannot resolve. Those rewrites are scoped to
HTML-derived formats only, so a `<u>` in a `.csv` or a `<!-- -->` in a `.md` —
which is the user's own text — is left untouched.

## Deploying

Push to a Git repository and import it into Vercel. `vercel.json` defines both
services and the routing between them; no dashboard configuration is needed.

Two things are easy to get wrong:

- The Python service receives the **original** request path, so the route is
  declared at `/api/convert` in `backend/main.py` — not at `/convert`.
- `uvicorn` is deliberately **not** in `requirements.txt`. Vercel's Python
  runtime loads the ASGI `app` object directly, so it is a local-only tool.

## Design

`DESIGN.md` defines the visual system and is the source of truth for any UI
change. Its "Quick Start → Tailwind v4" block must **not** be copied literally —
four of its token definitions are real bugs that fail silently rather than
erroring. `frontend/src/app/globals.css` documents each one at the top of the
file; read that comment before touching the token block.
