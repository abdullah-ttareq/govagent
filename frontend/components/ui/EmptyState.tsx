import type { ReactNode } from "react";

/** حالة فارغة موحّدة: ما الذي لا يوجد، وما الذي يفعله المستخدم بعدها. */
export default function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-md border border-dashed border-border-strong p-6 text-center">
      <p className="text-sm font-semibold">{title}</p>
      {hint && <p className="mt-2 text-xs leading-relaxed text-muted">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
