import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

const iranYekan = localFont({
  src: [
    {
      path: "./fonts/iranyekanwebregular.b95439c1.b95439c1.woff",
      weight: "400",
      style: "normal",
    },
    {
      path: "./fonts/iranyekanwebmedium.2d4f96e5.2d4f96e5.woff",
      weight: "500",
      style: "normal",
    },
    {
      path: "./fonts/iranyekanwebbold.cfb6e26c.woff2",
      weight: "700",
      style: "normal",
    },
    {
      path: "./fonts/iranyekanwebextrabold.9346e9a2.9346e9a2.woff",
      weight: "800",
      style: "normal",
    },
  ],
  variable: "--font-ui",
  display: "swap",
});

export const metadata: Metadata = {
  title: "دستیار اسناد",
  description: "چت هوشمند، منابع مستند و مدل‌های قابل انتخاب",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fa" dir="rtl" data-theme="dark">
      <body className={iranYekan.variable}>{children}</body>
    </html>
  );
}
