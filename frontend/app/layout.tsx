import type { Metadata, Viewport } from "next";
import { Cairo } from "next/font/google";
import AuthProvider from "@/components/AuthProvider";
import { THEME_INIT_SCRIPT } from "@/lib/theme";
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
    default: "GovMind — المساعد الذكي لمنسوبي الجهة",
    template: "%s · GovMind",
  },
  description: "مساعد ذكاء اصطناعي عام لموظفي الجهات الحكومية.",
  applicationName: "GovMind",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "GovMind",
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
  // لونان: المتصفح يختار بحسب إعداد الجهاز، و`applyTheme` يحدّثه عند تبديل
  // الموظف للوضع يدويًا.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#1e50c8" },
    { media: "(prefers-color-scheme: dark)", color: "#0a1020" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // `suppressHydrationWarning`: سكربت المظهر يضيف `data-theme` إلى هذا
    // العنصر قبل الإماهة، فيختلف عمّا رُسم على السيرفر — وهو اختلاف مقصود.
    <html
      lang="ar"
      dir="rtl"
      className={`${cairo.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* قبل أي أسلوب أو حزمة: يضبط الوضع فلا يومض الأبيض على من اختار
            الداكن. محتواه ثابت لا يأتي من مدخل مستخدم. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="font-sans min-h-full">
        <AuthProvider>{children}</AuthProvider>
        <ServiceWorkerRegistrar />
      </body>
    </html>
  );
}
