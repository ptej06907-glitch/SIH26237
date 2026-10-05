import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SourceX | SIH 2026 Prototype",
  description: "Offline cryptographic attribution and decryption provenance research prototype.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
