"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/components/AuthProvider";
import ErrorNotice from "@/components/ui/ErrorNotice";
import { OFFLINE_MESSAGE } from "@/lib/api";

/**
 * غلاف الصفحات المحمية: من ليس مسجَّلًا يُحوَّل إلى `/login`.
 *
 * حماية في الواجهة فقط — **ليست بديلًا عن حماية الـBackend.** المسارات
 * المحمية تفحص الرمز في كل طلب، وهذا هو الحاجز الحقيقي؛ ما هنا يمنع عرض
 * هيكل صفحة فارغة لمن لا جلسة له.
 *
 * حالة `offline` **لا تُحوَّل**: الجلسة قد تكون سليمة والسيرفر هو البعيد،
 * فيُعرض السبب وطريقا حلّه بدل طرد صامت إلى صفحة الدخول.
 */
export default function RequireAuth({ children }: { children: ReactNode }) {
  const { status, retrySession } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") {
      // replace لا push: صفحة محمية لا يُعاد إليها بزر الرجوع.
      router.replace("/login");
    }
  }, [status, router]);

  if (status === "offline") {
    return (
      <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-4">
        <h1 className="mb-4 text-lg font-bold">تعذّر الوصول إلى سيرفر جهتك</h1>
        <ErrorNotice
          failure={{ message: OFFLINE_MESSAGE, action: "settings" }}
          onRetry={retrySession}
        />
      </main>
    );
  }

  if (status !== "authenticated") {
    return (
      <div
        className="flex min-h-dvh items-center justify-center p-6"
        role="status"
        aria-live="polite"
      >
        <p className="flex items-center gap-3 text-sm text-muted">
          <span className="gv-spinner" aria-hidden="true" />
          {status === "checking"
            ? "جارٍ التحقق من الجلسة…"
            : "جارٍ التحويل إلى صفحة الدخول…"}
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
