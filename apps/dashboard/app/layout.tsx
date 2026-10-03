import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Concierge Control",
  description: "Configure and operate AI sales concierges.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-GB">
      <body>{children}</body>
    </html>
  );
}

