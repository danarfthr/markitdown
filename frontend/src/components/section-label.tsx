export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-label font-normal uppercase tracking-[0.12em] text-carbon-warm">
      {/* The signature 4px machined square — replaces conventional bullets. */}
      <span aria-hidden className="block size-1 shrink-0 bg-carbon-warm" />
      {children}
    </p>
  );
}
