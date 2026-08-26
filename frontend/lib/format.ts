/** أدوات عرض صغيرة مشتركة بين مكوّنات الواجهة. */

const relative = new Intl.RelativeTimeFormat("ar", { numeric: "auto" });
const dateOnly = new Intl.DateTimeFormat("ar", {
  day: "numeric",
  month: "long",
});

/**
 * يحوّل طابع الوقت القادم من الـBackend إلى `Date`.
 *
 * النصّ بلا لاحقة منطقة زمنية يُعامَل UTC: الـBackend يكتب أوقاته بـUTC،
 * ومن دون هذه الإضافة يفسّرها المتصفح توقيتًا محليًا فتظهر «قبل ٣ ساعات»
 * لرسالة أُرسلت للتو.
 */
function parseTimestamp(value: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

/** «الآن» · «قبل ٥ دقائق» · «أمس» · «١٢ أغسطس». */
export function formatRelativeTime(value: string): string {
  const date = parseTimestamp(value);
  if (Number.isNaN(date.getTime())) return "";

  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "الآن";

  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return relative.format(-minutes, "minute");

  const hours = Math.round(minutes / 60);
  if (hours < 24) return relative.format(-hours, "hour");

  const days = Math.round(hours / 24);
  if (days < 7) return relative.format(-days, "day");

  // أبعد من أسبوع: التاريخ أوضح من «قبل ٦ أسابيع».
  return dateOnly.format(date);
}
