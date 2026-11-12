import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Folium Agents | Talk to your EHR",
  description: "Talk to your EHR with read-only, evidence-grounded chat.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
