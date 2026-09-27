"""File -> Markdown conversion API.

Runs as a Vercel service (see vercel.json at the repo root). The service
receives the ORIGINAL request path, so the route below is declared at
/api/convert and not at /convert — Vercel routes /api/(.*) here without
stripping the prefix.
"""

from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from collections import defaultdict, deque

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
# These are re-exported from the package root (see markitdown/__init__.py
# __all__); importing them from markitdown._exceptions would reach into a
# private module.
from markitdown import (
    FileConversionException,
    MarkItDown,
    MissingDependencyException,
    StreamInfo,
    UnsupportedFormatException,
)
from markitdown.converters import ZipConverter

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

# Extensions MarkItDown routes to a converter whose optional dependency this
# deployment deliberately does not install. They are rejected with an honest
# 415 instead of being accepted and then failing with a misleading
# "corrupt or password-protected" 422.
#
#   .xls  needs the `xls` extra (xlrd). requirements.txt installs
#         [pdf,docx,pptx,xlsx] only — see the comment there.
#   .doc  legacy binary Word has no converter at all in MarkItDown.
#   .rtf  .odt  .svg  fall through to PlainTextConverter, which returns the
#         raw markup as "Markdown" — worse than an explicit refusal.
UNSUPPORTED_EXTENSIONS = frozenset({".xls", ".doc", ".rtf", ".odt", ".svg"})

# OOXML and EPUB files are ZIP containers, so they cannot be told apart from a
# plain archive by magic bytes. Instead the ZIP *member list* is inspected for
# the marker each format must contain. A renamed archive has none of these and
# is rejected, while a real document passes through untouched.
#
# This matters because MarkItDown registers a ZipConverter that recursively
# expands archives, and _get_stream_info_guesses() emits a SECOND `.zip` guess
# whenever magika disagrees with the declared extension — so an extension-only
# guard does not actually stop a renamed archive from being expanded.
_ZIP_CONTAINER_MARKERS: dict[str, tuple[str, ...]] = {
    ".docx": ("word/",),
    ".pptx": ("ppt/",),
    ".xlsx": ("xl/",),
    ".epub": ("META-INF/container.xml",),
}

# Converted Markdown is plain text with no image store behind it, so image
# references to local paths are always dead. Remote URLs still resolve, so they
# are left alone.
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_UNDERLINE_RE = re.compile(r"</?u(?:\s[^>]*)?>", re.I)
_SLIDE_COMMENT_RE = re.compile(r"<!--\s*Slide number:\s*(\d+)\s*-->")

# Formats whose converters build their output out of HTML, so a tag in the
# result is the converter's formatting rather than the user's text. Only these
# get the HTML rewrites below.
#
# Everything else is passed through nearly verbatim, so a `<u>` or `<!--` in a
# .md, .txt, .csv or .ipynb is the user's own data and rewriting it would
# corrupt the document. (The .ipynb converter in particular copies markdown
# cells through untouched, and the .csv/.xlsx cell writers round-trip text
# through HTML, which un-escapes any angle brackets a cell contained.)
_HTML_DERIVED_EXTENSIONS = frozenset(
    {".docx", ".pptx", ".xlsx", ".html", ".htm", ".epub"}
)


def _is_resolvable_url(src: str) -> bool:
    if src.startswith(("http://", "https://")):
        return True
    # MarkItDown truncates an oversized data URI to `data:image/png;base64...`
    # (see convert_img in its _markdownify.py), which is not a usable image. A
    # complete data URI always carries a comma before its payload.
    if src.startswith("data:"):
        return "," in src
    return False


def _is_zip_container(data: bytes) -> bool:
    """True if the bytes are readable as a ZIP archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return bool(archive.namelist())
    except Exception:
        return False


def _has_expected_marker(data: bytes, extension: str) -> bool:
    """True if `data` is a ZIP containing the marker `extension` requires."""
    markers = _ZIP_CONTAINER_MARKERS[extension]
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except Exception:
        return False

    for marker in markers:
        if marker.endswith("/"):
            if any(name.startswith(marker) for name in names):
                return True
        elif marker in names:
            return True
    return False


def _format_passthrough_markdown(markdown: str, extension: str) -> str:
    """Make raw JSON/XML legible.

    MarkItDown's PlainTextConverter returns JSON and XML verbatim, which
    collapses to a single unreadable line once rendered. Fencing it as code
    keeps the content byte-identical while making it display properly.
    """
    if extension == ".json":
        try:
            parsed = json.loads(markdown)
        except (ValueError, TypeError):
            # Not valid JSON; fence whatever came back rather than fail.
            pass
        else:
            markdown = json.dumps(parsed, indent=2, ensure_ascii=False)
    elif extension not in (".jsonl", ".xml"):
        return markdown

    # .jsonl is one object per line, so pretty-printing would merge records.

    if markdown.lstrip().startswith("```"):
        return markdown
    # Four-backtick fence: JSON/XML content can itself contain ``` runs.
    return f"````\n{markdown.strip()}\n````"


def _clean_markdown(markdown: str, extension: str) -> str:
    """Tidy converter output for human-readable rendering.

    MarkItDown targets LLM pipelines, so a few things it emits on purpose are
    wrong for a document preview:

    - The PPTX converter writes `<!-- Slide number: N -->` before every slide,
      and the DOCX and HTML converters map underline to a literal `<u>` tag.
      The preview renders Markdown without `rehype-raw` (deliberately, for
      XSS), so raw HTML is escaped and shown to the user as visible text.
    - Embedded images become `![alt](Picture1.jpg)`, but the response carries no
      image data, so those links are always broken.
    - JSON and XML come back as raw text.

    The HTML rewrites are confined to `_HTML_DERIVED_EXTENSIONS`; see the note
    there for why rewriting every format would be data loss.
    """
    if extension in _HTML_DERIVED_EXTENSIONS:
        if extension == ".pptx":
            markdown = _SLIDE_COMMENT_RE.sub(
                lambda m: f"\n\n## Slide {m.group(1)}\n", markdown
            )
        # Any remaining comment is converter bookkeeping the reader does not
        # need.
        markdown = _HTML_COMMENT_RE.sub("", markdown)

        # A real Word underline and the literal text "<u>x</u>" both arrive as
        # `<u>x</u>`, and are indistinguishable here, so underline is dropped
        # rather than guessed at. DESIGN.md has no underline in its type system.
        markdown = _UNDERLINE_RE.sub("", markdown)

    markdown = _replace_dead_images(markdown)
    markdown = _format_passthrough_markdown(markdown, extension)

    return _collapse_blank_runs(markdown)


def _replace_dead_images(markdown: str) -> str:
    """Turn image links that cannot resolve into visible alt text.

    Keep the alt text so no information is lost, drop the dead link.
    """

    def _replace(match: re.Match[str]) -> str:
        alt, src = match.group(1).strip(), match.group(2)
        if _is_resolvable_url(src):
            return match.group(0)
        return f"[image: {alt}]" if alt else "[image]"

    return _IMAGE_RE.sub(_replace, markdown)


def _collapse_blank_runs(markdown: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def _caused_by_missing_dependency(exc: FileConversionException) -> bool:
    """True if the failure was a converter missing an optional dependency.

    MarkItDown still matches a converter by extension when that converter's
    extra was never installed, then fails inside convert(). That is a
    deployment gap, not a malformed upload, so it must not be reported as
    "corrupt or password-protected".
    """
    attempts = [a for a in (getattr(exc, "attempts", None) or []) if a.exc_info]
    return bool(attempts) and all(
        isinstance(attempt.exc_info[1], MissingDependencyException)
        for attempt in attempts
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

# The ZipConverter recursively expands archives, including nested ones, which on
# a public endpoint is a zip-bomb / CPU-exhaustion vector. Removing it makes the
# guard defence-in-depth rather than the only line of defence: even if a request
# slips past the extension and marker checks, nothing will expand an archive.
#
# MarkItDown offers no public way to unregister a converter, so this reaches
# into `_converters`. A silent no-op would leave the endpoint exposed while
# looking guarded, so the removal is verified rather than assumed.
_converters_before = len(_converter._converters)
_converter._converters = [
    registration
    for registration in _converter._converters
    if not isinstance(registration.converter, ZipConverter)
]
if len(_converter._converters) != _converters_before - 1:
    raise RuntimeError(
        "Failed to remove MarkItDown's ZipConverter. Its internals changed; "
        "re-check that archives are not expanded before deploying."
    )


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

    if extension in UNSUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"{extension} files are not supported. Try saving it as PDF, DOCX or XLSX first.",
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

    # A .docx/.pptx/.xlsx/.epub is a ZIP container, so the declared extension
    # alone proves nothing: a renamed archive would otherwise be expanded by
    # the converter chain. Require the marker the format actually needs.
    if extension in _ZIP_CONTAINER_MARKERS:
        if not _is_zip_container(data) or not _has_expected_marker(data, extension):
            raise HTTPException(
                status_code=415,
                detail=(
                    f"That file is not a valid {extension.lstrip('.').upper()} document. "
                    "If it is an archive, upload the document inside it instead."
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
    except FileConversionException as exc:
        # Converters raise a wide variety of library-specific errors on
        # malformed input. A missing optional dependency is not a bad file,
        # though, and reporting it as one would be actively misleading.
        if _caused_by_missing_dependency(exc):
            raise HTTPException(
                status_code=415,
                detail="That file type is not supported.",
            ) from None
        raise HTTPException(
            status_code=422,
            detail="That file could not be converted. It may be corrupt or password-protected.",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=422,
            detail="That file could not be converted. It may be corrupt or password-protected.",
        ) from None

    markdown = _clean_markdown(result.markdown, extension)

    return PlainTextResponse(markdown, media_type="text/markdown")


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
