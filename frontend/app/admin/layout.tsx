import type { Metadata } from "next";

export const metadata: Metadata = { title: "لوحة مسؤول الجهة" };

// ⚠️ **النوع مكتوب يدويًا لا `LayoutProps<...>`.** الأخير يشتقّ من مسارات
// البناء الحالي، وبناء سطح المكتب لا يبني هذا المسار أصلًا
// (`pageExtensions` في `next.config.ts`) — فيصير النوع مرجعًا إلى مسار
// غير موجود ويفشل فحص الأنواع في ذلك البناء وحده.
export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
