"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import Button from "@/components/ui/Button";

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
      <p className="truncate text-sm font-semibold">{user.full_name}</p>
      <p className="truncate text-xs text-muted">
        {user.organization_name ?? "—"}
        {user.role === "admin" && " · مسؤول الجهة"}
      </p>

      {/* رابط اللوحة لمسؤول الجهة وحده. إخفاؤه راحة عرض لا حماية:
          مسارات اللوحة كلها تفرض الدور في السيرفر. */}
      {user.role === "admin" && (
        <Link
          href="/admin"
          className="gv-btn gv-btn--secondary mt-3 w-full"
        >
          لوحة الإدارة
        </Link>
      )}

      <div className="mt-2 flex gap-2">
        <Button
          variant="secondary"
          className="flex-1"
          isLoading={isSigningOut}
          loadingLabel="جارٍ الخروج…"
          onClick={handleSignOut}
        >
          تسجيل الخروج
        </Button>

        <Link
          href="/settings"
          className="gv-btn gv-btn--secondary shrink-0 !px-3"
          aria-label="الإعدادات"
          title="الإعدادات"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5">
            <path
              fill="currentColor"
              d="M10 6.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8m0 1.5a1.9 1.9 0 1 1 0 3.8 1.9 1.9 0 0 1 0-3.8"
            />
            <path
              fill="currentColor"
              d="m8.7 1.8 2.6 0c.5 0 .9.3 1 .8l.3 1.4q.5.2 1 .5l1.4-.5c.4-.2.9 0 1.2.4l1.3 2.2c.2.4.2.9-.2 1.2l-1.1.9q0 .3 0 .6l1.1.9c.4.3.4.8.2 1.2l-1.3 2.2c-.3.4-.8.6-1.2.4l-1.4-.5q-.5.3-1 .5l-.3 1.4c-.1.5-.5.8-1 .8l-2.6 0c-.5 0-.9-.3-1-.8l-.3-1.4q-.5-.2-1-.5l-1.4.5c-.4.2-.9 0-1.2-.4l-1.3-2.2c-.2-.4-.2-.9.2-1.2l1.1-.9q0-.3 0-.6l-1.1-.9c-.4-.3-.4-.8-.2-1.2l1.3-2.2c.3-.4.8-.6 1.2-.4l1.4.5q.5-.3 1-.5l.3-1.4c.1-.5.5-.8 1-.8m.4 1.5-.3 1.6-.5.2q-.6.2-1.2.6l-.4.3-1.6-.6-1 1.7 1.3 1.1-.1.5a5 5 0 0 0 0 1.4l.1.5-1.3 1.1 1 1.7 1.6-.6.4.3q.6.4 1.2.6l.5.2.3 1.6h2l.3-1.6.5-.2q.6-.2 1.2-.6l.4-.3 1.6.6 1-1.7-1.3-1.1.1-.5a5 5 0 0 0 0-1.4l-.1-.5 1.3-1.1-1-1.7-1.6.6-.4-.3a5 5 0 0 0-1.2-.6l-.5-.2-.3-1.6z"
            />
          </svg>
        </Link>
      </div>
    </div>
  );
}
