"use client";

import { memo } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

/*
 * This module exists to keep the Markdown parser off the critical path.
 *
 * react-markdown + remark-gfm is ~144 KB of the initial page load, and none of
 * it is needed until a file has actually converted. file-converter.tsx loads
 * this module through next/dynamic, so the parser is fetched only when a result
 * exists to render.
 *
 * It is a separate file rather than an inline dynamic import because the memo
 * and the hoisted plugin array below are the other half of the fix.
 */

type RemarkPlugins = React.ComponentProps<typeof Markdown>["remarkPlugins"];

/*
 * Module scope, deliberately. react-markdown builds a fresh unified processor
 * on every render (see createProcessor in its lib/index.js) and compares the
 * plugins by identity, so an inline `remarkPlugins={[remarkGfm]}` produces a
 * new array each render and forces a full re-parse of the document.
 *
 * That re-parse fired on every unrelated state change — clicking Copy, or
 * dragging a file back over the drop zone — and a document can be up to 4 MB.
 */
const REMARK_PLUGINS: RemarkPlugins = [remarkGfm];

/*
 * memo() so that re-renders of the parent that do not change `markdown` skip
 * this component entirely. react-markdown is not memoized internally.
 */
export const MarkdownPreview = memo(function MarkdownPreview({
  markdown,
}: {
  markdown: string;
}) {
  return (
    <article className="markdown-body">
      <Markdown remarkPlugins={REMARK_PLUGINS}>{markdown}</Markdown>
    </article>
  );
});
