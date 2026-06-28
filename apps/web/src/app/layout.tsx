import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="fa" dir="rtl" suppressHydrationWarning>
      <body>
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('theme')||'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){}`,
          }}
        />
        {children}
      </body>
    </html>
  );
}
