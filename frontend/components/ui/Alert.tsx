import type { ReactNode } from "react";

type AlertTone = "error" | "success" | "warning" | "info";

/**
 * رسالة موحّدة. رسائل الخطأ تحمل `role="alert"` فينطقها قارئ الشاشة فور
 * ظهورها، وبقية النبرات `role="status"` فلا تقاطع القراءة.
 */
export default function Alert({
  tone = "info",
  children,
  className = "",
}: {
  tone?: AlertTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`gv-alert gv-alert--${tone} ${className}`.trim()}
    >
      <span>{children}</span>
    </div>
  );
}
