import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/components/ui";

export const metadata: Metadata = { title: "Operations Copilot", description: "Enterprise AI operations assistant" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body><AuthProvider><ToastProvider>{children}</ToastProvider></AuthProvider></body>
    </html>
  );
}
