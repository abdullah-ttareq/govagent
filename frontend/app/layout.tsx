import type { Metadata, Viewport } from "next";
import { Cairo } from "next/font/google";
import AuthProvider from "@/components/AuthProvider";
import "./globals.css";

const cairo = Cairo({
  variable: "--font-arabic",
  subsets: ["arabic", "latin"],
  // الأوزان التي يستخدمها نظام التصميم فعلًا: نص عادي، وشبه عريض للتسميات
  // والأزرار، وعريض للعناوين. تحميل ما لا يُستخدم يبطئ أول عرض على الجوال.
  weight: ["400", "600", "700"],
  // النص يظهر بخط احتياطي فورًا بدل فراغ أثناء تحميل الخط.
  display: "swap",
});

export const metadata: Metadata = {
  title: "GovAgent — المساعد الذكي للموظف",
  description: "مساعد ذكاء اصطناعي عام لموظفي الجهات الحكومية.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#1f6f5c",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ar" dir="rtl" className={`${cairo.variable} h-full antialiased`}>
      <body className="font-sans min-h-full">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
