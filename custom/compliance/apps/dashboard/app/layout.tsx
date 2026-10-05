import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "MKA compliance dashboard", description: "Who has completed the annual officeholder training, and who to chase." };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">{children}</body>
    </html>
  );
}
