"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { SectionLabel } from "@/components/section-label";

/*
 * Vercel caps both request AND response bodies at 4.5 MB
 * (413 FUNCTION_PAYLOAD_TOO_LARGE). We gate at 4 MB so the request itself is
 * never the thing that trips the limit, and so the converted Markdown — which
 * for a text-heavy PDF can be about as large as its input — still fits in the
 * response.
 *
 * This is a UX gate only. The server enforces the same cap independently,
 * because anyone can bypass the browser.
 */
const MAX_FILE_BYTES = 4 * 1024 * 1024;

type Status =
  | { kind: "idle" }
  | { kind: "converting"; filename: string }
  | { kind: "done"; filename: string; markdown: string }
  | { kind: "error"; message: string };

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** `report.pdf` -> `report.md`, so the download has a sensible name. */
function toMarkdownFilename(filename: string) {
  const stem = filename.replace(/\.[^./\\]+$/, "") || "document";
  return `${stem}.md`;
}

export function FileConverter() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [isDragging, setIsDragging] = useState(false);
  const [copied, setCopied] = useState(false);
  const dragDepth = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Dropping on the window would otherwise make the browser navigate away to
  // the raw file, replacing the app entirely.
  useEffect(() => {
    const prevent = (event: DragEvent) => event.preventDefault();
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", prevent);
    return () => {
      window.removeEventListener("dragover", prevent);
      window.removeEventListener("drop", prevent);
    };
  }, []);

  const convert = useCallback(async (file: File) => {
    if (file.size > MAX_FILE_BYTES) {
      setStatus({
        kind: "error",
        message: `That file is ${formatBytes(file.size)}. The limit is ${formatBytes(
          MAX_FILE_BYTES,
        )} — try a smaller file.`,
      });
      return;
    }

    setStatus({ kind: "converting", filename: file.name });

    try {
      const body = new FormData();
      body.append("file", file);

      const response = await fetch("/api/convert", { method: "POST", body });

      if (!response.ok) {
        // The backend returns JSON errors; fall back to a generic message if
        // it ever returns something else (e.g. a platform-level 413).
        let message = `Conversion failed (${response.status}).`;
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload.detail) message = payload.detail;
        } catch {
          /* keep the generic message */
        }
        setStatus({ kind: "error", message });
        return;
      }

      const markdown = await response.text();

      if (markdown.trim().length === 0) {
        setStatus({
          kind: "error",
          message: "That file converted to nothing — it may be empty or image-only.",
        });
        return;
      }

      setStatus({ kind: "done", filename: file.name, markdown });
    } catch {
      setStatus({
        kind: "error",
        message: "Could not reach the converter. Check your connection and try again.",
      });
    }
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      dragDepth.current = 0;
      setIsDragging(false);
      const file = event.dataTransfer.files[0];
      if (file) void convert(file);
    },
    [convert],
  );

  const download = useCallback(() => {
    if (status.kind !== "done") return;
    const blob = new Blob([status.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = toMarkdownFilename(status.filename);
    anchor.click();
    URL.revokeObjectURL(url);
  }, [status]);

  const copy = useCallback(async () => {
    if (status.kind !== "done") return;
    try {
      await navigator.clipboard.writeText(status.markdown);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setStatus({
        kind: "error",
        message: "Copying was blocked by the browser. Use Download instead.",
      });
    }
  }, [status]);

  const reset = useCallback(() => {
    setStatus({ kind: "idle" });
    setCopied(false);
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const isConverting = status.kind === "converting";

  return (
    <section
      id="convert"
      className="mx-auto flex w-full max-w-page scroll-mt-32 flex-col gap-6 px-6 py-12"
    >
      <SectionLabel>Convert</SectionLabel>

      <div
        onDragEnter={(event) => {
          event.preventDefault();
          dragDepth.current += 1;
          setIsDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => {
          dragDepth.current -= 1;
          if (dragDepth.current <= 0) setIsDragging(false);
        }}
        onDrop={onDrop}
        className="relative"
      >
        {isDragging && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-cards border border-carbon-warm bg-vellum/90">
            <p className="text-body-sm text-carbon-warm">Drop a file to convert</p>
          </div>
        )}

        {/* The drop target is the signature 80px-radius card. */}
        <div className="flex flex-col items-center gap-6 rounded-cards border border-carbon-warm bg-paper-white px-6 py-24 text-center">
          <p className="text-subheading text-carbon-warm">
            {isConverting ? "Converting…" : "Drop a file, or choose one"}
          </p>
          <p className="max-w-md text-body-sm text-carbon-warm">
            PDF, Word, PowerPoint, Excel, HTML, CSV, JSON, XML, images and more.
            Up to {formatBytes(MAX_FILE_BYTES)}.
          </p>

          <div className="flex flex-wrap items-center justify-center gap-4">
            <label
              className={`rounded-pills bg-carbon-warm px-5.5 py-4.5 text-body-sm text-paper-white ${
                isConverting ? "cursor-not-allowed opacity-60" : "cursor-pointer"
              }`}
            >
              Choose file
              <input
                ref={inputRef}
                type="file"
                className="sr-only"
                disabled={isConverting}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void convert(file);
                  // Reset so re-picking the same file fires change again.
                  event.target.value = "";
                }}
              />
            </label>

            {status.kind !== "idle" && !isConverting && (
              <button
                type="button"
                onClick={reset}
                className="rounded-pills border border-carbon-warm px-5.5 py-4.5 text-body-sm text-carbon-warm"
              >
                Clear
              </button>
            )}
          </div>

          {isConverting && (
            <p className="text-label text-mercury">{status.filename}</p>
          )}
        </div>
      </div>

      {status.kind === "error" && (
        <p className="text-body-sm text-carbon-warm" role="alert">
          {status.message}
        </p>
      )}

      {status.kind === "done" && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <p className="text-label uppercase tracking-[0.12em] text-mercury">
              {status.filename}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void copy()}
                className="rounded-pills border border-carbon-warm px-5.5 py-4.5 text-body-sm text-carbon-warm"
              >
                {copied ? "Copied" : "Copy"}
              </button>
              <button
                type="button"
                onClick={download}
                className="rounded-pills bg-carbon-warm px-5.5 py-4.5 text-body-sm text-paper-white"
              >
                Download .md
              </button>
            </div>
          </div>

          <div className="rounded-body border border-carbon-warm bg-paper-white p-5">
            <article className="markdown-body">
              <Markdown remarkPlugins={[remarkGfm]}>{status.markdown}</Markdown>
            </article>
          </div>
        </div>
      )}
    </section>
  );
}
