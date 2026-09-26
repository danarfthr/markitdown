"""File -> Markdown conversion API.

Runs as a Vercel service (see vercel.json at the repo root). The service
receives the ORIGINAL request path, so the route below is declared at
/api/convert and not at /convert — Vercel routes /api/(.*) here without
stripping the prefix.
"""

from __future__ import annotations

import io
import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
# UnsupportedFormatException is re-exported from the package root (see
# markitdown/__init__.py __all__); importing it from markitdown._exceptions
# would reach into a private module.
from markitdown import MarkItDown, StreamInfo, UnsupportedFormatException

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

# Mirrors MAX_FILE_BYTES in frontend/src/components/file-converter.tsx.
# The browser gate is UX only — anyone can bypass it, so this is the real one.
# Vercel caps request AND response bodies at 4.5 MB, so exceeding this would
# fail at the platform level with a much less helpful error anyway.
MAX_FILE_BYTES = 4 * 1024 * 1024

# Best-effort abuse control. See RATE LIMIT CAVEAT below.
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60

# Archives are rejected by DECLARED EXTENSION, deliberately not by magic bytes.
# OOXML files (.docx/.pptx/.xlsx) are themselves ZIP containers, so sniffing for
# "PK\x03\x04" would reject the site's entire core feature set. MarkItDown ships
# a ZipConverter that recursively expands archives, which on a public endpoint is
# a zip-bomb / CPU-exhaustion vector, so the archive extensions are blocked and
# the OOXML ones are allowed through to their specific converters.
BLOCKED_EXTENSIONS = frozenset(
    {
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".jar",
        ".war",
        ".iso",
        ".cab",
    }
)

# ---------------------------------------------------------------------------
# Converter singleton
# ---------------------------------------------------------------------------

# Constructing MarkItDown loads the magika ONNX model (~24 MB of onnxruntime),
# which is far too expensive to repeat per request. Built once per instance and
# reused across invocations.
#
# enable_plugins is left at its default (False): this endpoint parses untrusted
# uploads, and plugins are arbitrary third-party code.
_converter = MarkItDown()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

# RATE LIMIT CAVEAT: this is in-process memory. On Vercel Fluid compute an
# instance may be reused or replaced at any time, and multiple instances run
# concurrently, so this is an approximate per-instance throttle — NOT a global
# quota. It blunts casual abuse; it does not stop a determined attacker.
# A durable limit needs shared state (e.g. Upstash Redis) or Vercel WAF.
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    # x-forwarded-for is set by Vercel's proxy. Take the left-most entry, which
    # is the originating client.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request) -> None:
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    bucket = _hits[_client_key(request)]

    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_REQUESTS:
        retry_after = int(bucket[0] + RATE_LIMIT_WINDOW_SECONDS - now) + 1
        raise HTTPException(
            status_code=429,
            detail="Too many conversions from this address. Please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )

    bucket.append(now)

    # Bound the dict so a flood of distinct keys cannot grow it without limit.
    if len(_hits) > 10_000:
        for key in [k for k, v in _hits.items() if not v]:
            del _hits[key]


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="markitdown-api")


@app.post("/api/convert")
async def convert(request: Request, file: UploadFile = File(...)) -> PlainTextResponse:
    _check_rate_limit(request)

    filename = file.filename or "upload"
    extension = os.path.splitext(filename)[1].lower()

    if extension in BLOCKED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Archive files are not supported. Upload the document inside it instead.",
        )

    data = await file.read()

    if len(data) == 0:
        raise HTTPException(status_code=400, detail="That file is empty.")

    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"That file is {len(data) / (1024 * 1024):.1f} MB. "
                f"The limit is {MAX_FILE_BYTES // (1024 * 1024)} MB."
            ),
        )

    try:
        # StreamInfo carries the original filename and extension through the
        # upload. Without it MarkItDown has only an anonymous byte stream and
        # format detection is far less reliable — an .xlsx with no name is
        # just a ZIP.
        result = _converter.convert(
            io.BytesIO(data),
            stream_info=StreamInfo(extension=extension, filename=filename),
        )
    except UnsupportedFormatException:
        raise HTTPException(
            status_code=415,
            detail="That file type is not supported.",
        ) from None
    except Exception:
        # Converters raise a wide variety of library-specific errors on
        # malformed input. None of them should surface a stack trace to the
        # client, and all of them mean the same thing to the user.
        raise HTTPException(
            status_code=422,
            detail="That file could not be converted. It may be corrupt or password-protected.",
        ) from None

    return PlainTextResponse(result.markdown, media_type="text/markdown")


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
