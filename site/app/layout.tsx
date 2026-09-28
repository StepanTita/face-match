import type { Metadata } from "next";
import { Zilla_Slab, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const zillaSlab = Zilla_Slab({
  variable: "--font-zilla",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
});

const jetBrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "facematch",
  description:
    "facematch — point it at a messy archive, get structured results back.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${zillaSlab.variable} ${jetBrainsMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
