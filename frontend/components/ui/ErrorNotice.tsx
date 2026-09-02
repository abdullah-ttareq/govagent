"use client";

import Link from "next/link";
import Alert from "@/components/ui/Alert";
import Button from "@/components/ui/Button";
import type { Failure } from "@/lib/errors";

/**
 * رسالة خطأ ومعها الإجراء الذي يفيد فعلًا في هذه الحالة تحديدًا.
 *
 * زر «إعادة المحاولة» تحت خطأ اشتراك منتهٍ لا يفعل شيئًا سوى تكرار الرفض،
 * ورابط الإعدادات تحت خطأ صلاحية لا علاقة له بالسبب — لذلك الإجراء يأتي
 * من تصنيف الخطأ في `lib/errors.ts` لا من مكان الاستدعاء.
 */
export default function ErrorNotice({
  failure,
  onRetry,
  className = "",
}: {
  failure: Failure;
  /** يُعرض زر إعادة المحاولة إن مُرِّر وكان التصنيف يسمح به. */
  onRetry?: () => void;
  className?: string;
}) {
  const showRetry = onRetry && (failure.action === "retry" || failure.action === "settings");

  return (
    <div className={className}>
      <Alert tone="error">{failure.message}</Alert>

      {(showRetry || failure.action === "settings") && (
        <div className="mt-3 flex flex-wrap gap-2">
          {showRetry && (
            <Button variant="secondary" onClick={onRetry}>
              إعادة المحاولة
            </Button>
          )}

          {failure.action === "settings" && (
            <Link href="/settings" className="gv-btn gv-btn--ghost">
              ضبط رابط السيرفر
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
