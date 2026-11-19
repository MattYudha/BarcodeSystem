import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Providers } from "@/components/app/providers";
import "./globals.css";

const sans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Bhavia Inventory", template: "%s · Bhavia Inventory" },
  description: "Sistem inventaris barcode Bhavia International Tailor",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f766e",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="id" className={`${sans.variable} ${mono.variable} h-full antialiased`}>
      <body className="min-h-full bg-muted/40">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
