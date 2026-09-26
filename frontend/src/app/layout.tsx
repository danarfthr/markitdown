import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

/*
 * "T1 Sans" is proprietary and not installable. Inter is the substitute
 * DESIGN.md explicitly sanctions for its "geometric neutrality".
 * Weight 300 must be requested explicitly — it carries every display headline.
 */
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Markitdown",
  description: "Convert any file to Markdown.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
