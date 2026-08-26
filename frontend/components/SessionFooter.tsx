"use client";

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

      <Button
        variant="secondary"
        block
        className="mt-3"
        isLoading={isSigningOut}
        loadingLabel="جارٍ الخروج…"
        onClick={handleSignOut}
      >
        تسجيل الخروج
      </Button>
    </div>
  );
}
