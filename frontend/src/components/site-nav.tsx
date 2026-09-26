"use client";

import { useEffect, useState } from "react";

const LINKS = [
  { href: "#convert", label: "Convert" },
  { href: "#format", label: "Format" },
] as const;

export function SiteNav() {
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    const targets = LINKS.map((link) =>
      document.getElementById(link.href.slice(1)),
    ).filter((element): element is HTMLElement => element !== null);

    if (targets.length === 0) return;

    // A narrow band near the top of the viewport decides which section counts
    // as current, so a link lights up once its heading has actually passed
    // under the pill rather than the moment the section enters view.
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(`#${entry.target.id}`);
        }
      },
      { rootMargin: "-25% 0px -65% 0px" },
    );

    targets.forEach((target) => observer.observe(target));
    return () => observer.disconnect();
  }, []);

  return (
    /*
     * Three layers, and each one is load-bearing:
     *
     *  1. This wrapper is sticky and spans the full width, but is deliberately
     *     TRANSPARENT — DESIGN.md wants a floating pill, not a full-width bar.
     *  2. It is also pointer-events-none. Without that it would be an invisible
     *     full-width strip swallowing every click in the top ~100px of the page.
     *  3. Sticky lives here, not on the pill: `position: sticky` is bounded by
     *     its containing block, so a w-fit pill inside a self-sized wrapper
     *     would never move.
     *
     * The inner flex row right-aligns the pill to the content column, matching
     * DESIGN.md's "floating dark pill anchored to the top-right".
     */
    <div className="pointer-events-none sticky top-0 z-50 w-full px-4 pt-6 pb-3 sm:px-6">
      <div className="mx-auto flex w-full max-w-page justify-end">
        <nav
          aria-label="Primary"
          className="pointer-events-auto flex w-fit items-center gap-2 rounded-nav bg-carbon-warm px-4 py-3.5 text-body-sm text-paper-white sm:gap-6 sm:px-6"
        >
          <span className="flex items-center gap-2">
            <span aria-hidden className="block size-1 shrink-0 bg-paper-white" />
            Markitdown
          </span>
          <ul className="flex items-center gap-1 sm:gap-4">
            {LINKS.map((link) => {
              const isActive = active === link.href;
              return (
                <li key={link.href}>
                  {/* min-h-11 keeps the tap target at 44px on touch screens. */}
                  <a
                    href={link.href}
                    aria-current={isActive ? "location" : undefined}
                    onClick={() => setActive(link.href)}
                    className={`flex min-h-11 items-center rounded-buttons px-3 underline-offset-4 transition-opacity hover:underline ${
                      isActive ? "opacity-100" : "opacity-70 hover:opacity-100"
                    }`}
                  >
                    {link.label}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </div>
  );
}
