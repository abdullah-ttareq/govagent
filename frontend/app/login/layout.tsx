import type { Metadata } from "next";

export const metadata: Metadata = { title: "تسجيل الدخول" };

// الصفحة نفسها مكوّن عميل، و`metadata` لا تُصدَّر من مكوّن عميل — فالغلاف
// موجود لحمل العنوان وحده، ولا يضيف عنصرًا إلى الشجرة.
export default function LoginLayout({ children }: LayoutProps<"/login">) {
  return children;
}
