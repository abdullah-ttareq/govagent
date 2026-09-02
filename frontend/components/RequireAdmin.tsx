"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useAuth } from "@/components/AuthProvider";
import Alert from "@/components/ui/Alert";

/**
 * يقصر المحتوى على مسؤول الجهة.
 *
 * **يمنع برسالة ولا يحوّل:** الموظف الذي فتح الرابط قصدًا أو بالخطأ يستحق
 * أن يعرف لماذا مُنع؛ تحويله صامتًا إلى الصفحة الرئيسية يبدو عطلًا.
 *
 * وهذه حماية عرض لا حماية وصول: `GET /api/users` و `GET /api/audit-logs`
 * و `GET .../subscription` كلها تفرض الدور في السيرفر عبر `AdminUser`،
 * فإخفاء الصفحة لا يمنح بيانات، وإظهارها لا يكشف شيئًا.
 */
export default function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth();

  // `RequireAuth` يغلّف هذه الصفحة، فالوصول إلى هنا يعني جلسة قائمة.
  if (!user) return null;

  if (user.role !== "admin") {
    return (
      <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-4">
        <h1 className="mb-4 text-lg font-bold">هذه الصفحة لمسؤول الجهة</h1>
        <Alert tone="error">
          لوحة الإدارة متاحة لمسؤول الجهة فقط، وحسابك مسجَّل بصفة «موظف». إن
          كنت تحتاج صلاحية الإدارة فراجع مسؤول النظام في جهتك.
        </Alert>
        <Link href="/" className="gv-btn gv-btn--secondary mt-4">
          العودة إلى المحادثات
        </Link>
      </main>
    );
  }

  return <>{children}</>;
}
