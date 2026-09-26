import { FileConverter } from "@/components/file-converter";
import { SectionLabel } from "@/components/section-label";
import { SiteNav } from "@/components/site-nav";

const FORMATS = [
  {
    title: "Documents",
    body: "PDF, Word, PowerPoint and Excel, converted through Microsoft's MarkItDown.",
  },
  {
    title: "Structured data",
    body: "HTML, CSV, JSON, XML and RSS become clean Markdown tables and lists.",
  },
  {
    title: "Nothing is stored",
    body: "Your file is converted in memory and returned. It is never written to disk.",
  },
];

export default function Home() {
  return (
    <>
      <SiteNav />

      <main className="flex flex-1 flex-col">
        {/*
         * Flat vellum hero. DESIGN.md's reference hero is full-bleed industrial
         * photography, but it also forbids abstract graphics and illustrations —
         * so with no licensed photograph to hand, the flat canvas is the
         * honest reading of the system rather than a decorative stand-in.
         */}
        <header className="mx-auto w-full max-w-page px-6 pt-24 pb-12">
          <SectionLabel>Any file to Markdown</SectionLabel>
          <h1 className="mt-6 max-w-3xl text-display text-carbon-warm">
            Convert a file the way a specification sheet reads.
          </h1>
          <p className="mt-6 max-w-xl text-body text-carbon-warm">
            Drop in a PDF, a Word document, a spreadsheet or a plain text file.
            You get clean Markdown back, ready to copy or download.
          </p>
        </header>

        <FileConverter />

        <section
          id="format"
          className="mx-auto w-full max-w-page scroll-mt-32 px-6 pt-12 pb-24"
        >
          <SectionLabel>Format</SectionLabel>
          <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-3">
            {FORMATS.map((item) => (
              <div
                key={item.title}
                className="rounded-body border border-carbon-warm bg-paper-white p-[22px]"
              >
                <h2 className="text-subheading text-carbon-warm">
                  {item.title}
                </h2>
                <p className="mt-2 text-body-sm text-carbon-warm">
                  {item.body}
                </p>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="w-full bg-onyx-depth px-6 pt-12 pb-[30px]">
        <div className="mx-auto flex max-w-page flex-wrap items-center justify-between gap-4">
          <p className="text-body-sm text-paper-white">Markitdown</p>
          <p className="text-body-sm text-paper-white">
            Powered by Microsoft MarkItDown.
          </p>
          <p className="text-body-sm text-paper-white">
            Made by{" "}
            <a
              href="https://danar.app"
              target="_blank"
              rel="noreferrer noopener"
              className="underline underline-offset-4"
            >
              danar.app
            </a>
          </p>
        </div>
      </footer>
    </>
  );
}
