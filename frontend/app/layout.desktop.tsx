import type { Metadata, Viewport } from "next";
import { Cairo } from "next/font/google";
import { THEME_INIT_SCRIPT } from "@/lib/theme";
import "./globals.css";

/**
 * الهيكل الجذري لبناء **سطح المكتب** وحده.
 *
 * ⚠️ **لماذا ملف منفصل باسم `layout.desktop.tsx`؟** بناء سطح المكتب يضبط
 * `pageExtensions: ["desktop.tsx"]` في `next.config.ts`، فلا يرى Next من
 * شجرة `app/` إلا الملفات المنتهية بهذا الامتداد. النتيجة أن التصدير
 * الساكن الذي يُثبَّت على جهاز العميل **لا يحتوي صفحة دخول ولا لوحة إدارة
 * ولا صفحة إعدادات سيرفر أصلًا** — لا مخفيّةً بشرط في الشيفرة، بل غير
 * مبنيّة. وهذا ما يجعل شرط «لا لفظ جهة ولا مسؤول في التطبيق المثبَّت»
 * قابلًا للفحص آليًا لا وعدًا.
 *
 * الفروق عن هيكل الويب:
 *
 * * **لا `AuthProvider`**: لا تسجيل دخول في التطبيق المثبَّت. الربط تمّ من
 *   الإضافة، والـRuntime يحمل بيان اعتماد الجهاز.
 * * **لا `ServiceWorkerRegistrar`**: عاملُ خدمة يخزّن نسخة من الصفحة، ونحن
 *   نخدمها من القرص المحلي أصلًا — فلا يزيد إلا احتمال عرض نسخة قديمة بعد
 *   تحديث GovMind.
 * * **لا `manifest.webmanifest`**: التطبيق مثبَّت على ويندوز لا مضاف إلى
 *   شاشة هاتف.
 */

const cairo = Cairo({
  variable: "--font-arabic",
  subsets: ["arabic", "latin"],
  weight: ["400", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "GovMind", template: "%s · GovMind" },
  description: "مساعد ذكي يعمل على هذا الجهاز.",
  applicationName: "GovMind",
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#1e50c8" },
    { media: "(prefers-color-scheme: dark)", color: "#0a1020" },
  ],
};

export default function DesktopRootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // `suppressHydrationWarning`: سكربت المظهر يضيف `data-theme` قبل
    // الإماهة، وهو اختلاف مقصود عمّا رُسم عند البناء.
    <html
      lang="ar"
      dir="rtl"
      className={`${cairo.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="font-sans min-h-full">{children}</body>
    </html>
  );
}
