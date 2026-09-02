import DesktopApp from "@/components/desktop/DesktopApp";

/**
 * الصفحة الوحيدة في بناء سطح المكتب.
 *
 * ⚠️ **لا `RequireAuth` ولا تحويل إلى `/login`.** العميل سجّل دخوله في
 * الإضافة، والـRuntime ربط هذا الجهاز. طلبُ دخول ثانٍ هنا هو العطل الذي
 * أُصلح، و`/login/` **غير موجودة في هذا التصدير أصلًا**.
 */
export default function DesktopHome() {
  return <DesktopApp />;
}
