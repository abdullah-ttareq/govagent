/**
 * مسارات مسؤول الجهة — موجودة فعلًا في `backend/app/api/users.py` و
 * `backend/app/api/organizations.py`.
 *
 * لا يُرسل أي نداء هنا `organization_id` في جسم الطلب: الجهة تُشتق من رمز
 * الدخول في السيرفر، ومعرّف الجهة في مسار الاشتراك يأتي من `/api/auth/me`.
 */

import { apiRequest } from "@/lib/api";
import type { AuthUser, UserRole } from "@/lib/auth";

/** `UserOut` نفسه الذي تعيده المصادقة. */
export type DirectoryUser = AuthUser;

type UserListResponse = {
  users: DirectoryUser[];
  total: number;
};

/** يطابق `SubscriptionOut` في `backend/app/schemas/governance.py`. */
export type Subscription = {
  organization_id: number;
  status: "active" | "expired" | "suspended";
  seats: number;
  seats_used: number;
  seats_available: number;
  starts_at: string;
  expires_at: string;
  is_usable: boolean;
  blocked_reason: string | null;
};

export function listUsers(
  token: string,
  signal?: AbortSignal,
): Promise<UserListResponse> {
  return apiRequest<UserListResponse>("/api/users", { token, signal });
}

export function createUser(
  token: string,
  payload: {
    email: string;
    full_name: string;
    role: UserRole;
    password: string;
  },
): Promise<DirectoryUser> {
  return apiRequest<DirectoryUser>("/api/users", {
    method: "POST",
    body: payload,
    token,
  });
}

/**
 * تعديل موظف. الحقول المتروكة فارغة لا تتغيّر، والبريد غير قابل للتعديل
 * أصلًا — هو هوية الدخول ومرجع سجل التدقيق.
 */
export function updateUser(
  token: string,
  userId: number,
  patch: {
    full_name?: string;
    role?: UserRole;
    is_active?: boolean;
    password?: string;
  },
): Promise<DirectoryUser> {
  return apiRequest<DirectoryUser>(`/api/users/${userId}`, {
    method: "PATCH",
    body: patch,
    token,
  });
}

/**
 * **تعطيل لا حذف.** `DELETE /api/users/{id}` يضع `is_active = 0` ولا يحذف
 * الصف: المستخدم مرتبط بمحادثاته وملفاته وسجل تدقيقه، وحذفه يترك تاريخًا
 * بلا صاحب. لا يوجد في الـBackend مسار حذف نهائي للموظف، ولم يُخترع هنا.
 */
export function disableUser(
  token: string,
  userId: number,
): Promise<DirectoryUser> {
  return apiRequest<DirectoryUser>(`/api/users/${userId}`, {
    method: "DELETE",
    token,
  });
}

export function getSubscription(
  token: string,
  organizationId: number,
  signal?: AbortSignal,
): Promise<Subscription> {
  return apiRequest<Subscription>(
    `/api/organizations/${organizationId}/subscription`,
    { token, signal },
  );
}

/* ---------------------------------------------------------------------------
   تحقق أوّلي في الواجهة — نفس حدود الـBackend
   --------------------------------------------------------------------------- */

/** يطابق `MIN_PASSWORD_LENGTH` في `backend/app/core/security.py`. */
export const MIN_PASSWORD_LENGTH = 8;

/** يطابق `MAX_PASSWORD_BYTES`. الحرف العربي بايتان، فالفحص بالبايت لا بالحرف. */
export const MAX_PASSWORD_BYTES = 72;

export function validateFullName(value: string): string | null {
  const cleaned = value.trim();
  if (!cleaned) return "أدخل اسم الموظف الكامل.";
  if (cleaned.length > 200) return "الاسم أطول من ٢٠٠ حرف.";
  return null;
}

export function validateNewPassword(value: string): string | null {
  if (value.trim().length < MIN_PASSWORD_LENGTH) {
    return `كلمة المرور قصيرة. الحد الأدنى ${MIN_PASSWORD_LENGTH} أحرف.`;
  }
  if (new TextEncoder().encode(value).length > MAX_PASSWORD_BYTES) {
    return (
      `كلمة المرور أطول من الحد المسموح (${MAX_PASSWORD_BYTES} بايت). ` +
      "الحروف العربية تشغل بايتين لكل حرف، فاختصرها."
    );
  }
  return null;
}

/* ---------------------------------------------------------------------------
   عرض
   --------------------------------------------------------------------------- */

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "مسؤول الجهة",
  employee: "موظف",
};

export const SUBSCRIPTION_LABELS: Record<Subscription["status"], string> = {
  active: "فعّال",
  expired: "منتهٍ",
  suspended: "موقوف",
};

/** عدد الأيام حتى الانتهاء، وسالب إن كان قد انتهى. */
export function daysUntil(isoDate: string): number {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(isoDate);
  const target = new Date(hasZone ? isoDate : `${isoDate}Z`).getTime();
  if (Number.isNaN(target)) return 0;
  return Math.ceil((target - Date.now()) / 86_400_000);
}

const fullDate = new Intl.DateTimeFormat("ar", {
  year: "numeric",
  month: "long",
  day: "numeric",
});

export function formatDate(isoDate: string): string {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(isoDate);
  const date = new Date(hasZone ? isoDate : `${isoDate}Z`);
  return Number.isNaN(date.getTime()) ? "—" : fullDate.format(date);
}
