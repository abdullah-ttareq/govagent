import type { Metadata, Viewport } from "next";
import { Cairo } from "next/font/google";
import AuthProvider from "@/components/AuthProvider";
import ServiceWorkerRegistrar from "@/components/ServiceWorkerRegistrar";
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
  // القالب يضيف اسم التطبيق إلى عنوان كل صفحة، فيبقى التبويب مميَّزًا حين
  // يفتح الموظف أكثر من صفحة.
  title: {
    default: "GovAgent — المساعد الذكي للموظف",
    template: "%s · GovAgent",
  },
  description: "مساعد ذكاء اصطناعي عام لموظفي الجهات الحكومية.",
  applicationName: "GovAgent",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "GovAgent",
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/icons/apple-touch-icon.png",
  },
  // شبكة داخلية لجهة حكومية: لا فائدة من فهرسة هذه الصفحات.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // بلا `maximumScale`: منع التكبير يقطع على ضعاف البصر وسيلتهم الوحيدة.
  themeColor: "#1f6f5c",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ar" dir="rtl" className={`${cairo.variable} h-full antialiased`}>
      <body className="font-sans min-h-full">
        <AuthProvider>{children}</AuthProvider>
        <ServiceWorkerRegistrar />
      </body>
    </html>
  );
}
