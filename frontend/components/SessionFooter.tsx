"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import Button from "@/components/ui/Button";
import ThemeToggle from "@/components/ThemeToggle";

/** بطاقة الموظف الحالي وزر الخروج، أسفل الشريط الجانبي. */
export default function SessionFooter() {
  const { user, signOut } = useAuth();
  const [isSigningOut, setIsSigningOut] = useState(false);

  if (!user) return null;

  async function handleSignOut() {
    setIsSigningOut(true);
    await signOut();
    // بلا إطفاء المؤشّر: RequireAuth يحوّل إلى /login فور تغيّر الحالة.
  }

  return (
    <div className="border-t border-border-subtle p-3">
      {/* بطاقة الموظف: حرف اسمه ثم الاسم والجهة — توازن محاذاة الترويسة أعلى. */}
      <div className="gv-brand mb-3">
        <span className="gv-brand__mark !bg-surface-muted !text-foreground" aria-hidden="true">
          {user.full_name.trim().charAt(0)}
        </span>
        <div className="min-w-0">
          {/* الاسم كاملًا: `break-words` يلتف عند الحاجة بدل `truncate` الذي
              يبتر أسماءً عربية مركّبة. والشريط لا يتّسع لأن الحاوية `min-w-0`. */}
          <p className="text-sm font-semibold leading-snug break-words">
            {user.full_name}
          </p>
          {/* الوصف يلتف إلى سطرين بحدّ أقصى ثم يُقصّ — سطران يكفيان لاسم
              جهة طويل، وما زاد يطيل البطاقة بلا فائدة. */}
          <p className="gv-clamp-2 text-xs leading-snug text-muted">
            {user.organization_name ?? "—"}
            {user.role === "admin" && " · مسؤول الجهة"}
          </p>
        </div>
      </div>

      {/* رابط اللوحة لمسؤول الجهة وحده. إخفاؤه راحة عرض لا حماية:
          مسارات اللوحة كلها تفرض الدور في السيرفر. */}
      {user.role === "admin" && (
        <Link href="/admin" className="gv-btn gv-btn--secondary mb-2 w-full">
          لوحة الإدارة
        </Link>
      )}

      {/* صفّ الإجراءات: الإعدادات والخروج بالوزن نفسه، ومبدّل المظهر زرّ
          أيقونة صغير بجانبهما — إعدادٌ ثانوي لا يزاحم الاثنين. */}
      <div className="flex items-stretch gap-2">
        <ThemeToggle />
        <Link
          href="/settings"
          className="gv-btn gv-btn--ghost flex-1 justify-center gap-2 !px-2"
          title="الإعدادات"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4">
            <path
              fill="currentColor"
              d="M10 6.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8m0 1.5a1.9 1.9 0 1 1 0 3.8 1.9 1.9 0 0 1 0-3.8"
            />
            <path
              fill="currentColor"
              d="m8.7 1.8 2.6 0c.5 0 .9.3 1 .8l.3 1.4q.5.2 1 .5l1.4-.5c.4-.2.9 0 1.2.4l1.3 2.2c.2.4.2.9-.2 1.2l-1.1.9q0 .3 0 .6l1.1.9c.4.3.4.8.2 1.2l-1.3 2.2c-.3.4-.8.6-1.2.4l-1.4-.5q-.5.3-1 .5l-.3 1.4c-.1.5-.5.8-1 .8l-2.6 0c-.5 0-.9-.3-1-.8l-.3-1.4q-.5-.2-1-.5l-1.4.5c-.4.2-.9 0-1.2-.4l-1.3-2.2c-.2-.4-.2-.9.2-1.2l1.1-.9q0-.3 0-.6l-1.1-.9c-.4-.3-.4-.8-.2-1.2l1.3-2.2c.3-.4.8-.6 1.2-.4l1.4.5q.5-.3 1-.5l.3-1.4c.1-.5.5-.8 1-.8m.4 1.5-.3 1.6-.5.2q-.6.2-1.2.6l-.4.3-1.6-.6-1 1.7 1.3 1.1-.1.5a5 5 0 0 0 0 1.4l.1.5-1.3 1.1 1 1.7 1.6-.6.4.3q.6.4 1.2.6l.5.2.3 1.6h2l.3-1.6.5-.2q.6-.2 1.2-.6l.4-.3 1.6.6 1-1.7-1.3-1.1.1-.5a5 5 0 0 0 0-1.4l-.1-.5 1.3-1.1-1-1.7-1.6.6-.4-.3a5 5 0 0 0-1.2-.6l-.5-.2-.3-1.6z"
            />
          </svg>
          الإعدادات
        </Link>

        <Button
          variant="ghost"
          className="flex-1 justify-center !px-2"
          isLoading={isSigningOut}
          loadingLabel="جارٍ الخروج…"
          onClick={handleSignOut}
        >
          الخروج
        </Button>
      </div>
    </div>
  );
}
