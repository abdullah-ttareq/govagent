import type { Metadata } from "next";
import { Cairo } from "next/font/google";
import "./globals.css";

const cairo = Cairo({
  variable: "--font-arabic",
  subsets: ["arabic", "latin"],
});

export const metadata: Metadata = {
  title: "GovAgent — المساعد الذكي للموظف",
  description: "مساعد ذكاء اصطناعي عام لموظفي الجهات الحكومية.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ar" dir="rtl" className={`${cairo.variable} h-full antialiased`}>
      <body className="font-sans min-h-full">{children}</body>
    </html>
  );
}
