/**
 * المصادقة: نداءات مسارات `/api/auth` وتخزين رمز الدخول.
 *
 * المسارات موجودة فعلًا في الـBackend (`backend/app/api/auth.py`) ولا يُخترع
 * هنا شيء: `POST /api/auth/login` و `GET /api/auth/me` و
 * `POST /api/auth/logout`.
 */

import { apiRequest } from "@/lib/api";

export type UserRole = "admin" | "employee";

/** يطابق `UserOut` في `backend/app/schemas/auth.py`. */
export type AuthUser = {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  organization_id: number;
  organization_name: string | null;
  is_active: boolean;
};

/** يطابق `TokenResponse` في `backend/app/schemas/auth.py`. */
export type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AuthUser;
};

export type LogoutResponse = { detail: string };

const TOKEN_KEY = "govagent.access_token";

/**
 * التخزين في `localStorage`.
 *
 * هذا اختيار MVP واعٍ: `localStorage` مقروء من JavaScript فهو عرضة لـXSS،
 * والبديل الصحيح كوكي `HttpOnly` يضبطه السيرفر. الـBackend اليوم يعيد الرمز
 * في جسم الرد لا في كوكي، فالتغيير يستلزم تعديل الـBackend وهو خارج نطاق
 * P3-01. نقطة التبديل الوحيدة هي الدوال الثلاث أدناه.
 */
export function readStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    // وضع التصفح الخاص قد يمنع التخزين — الجلسة تعمل في الذاكرة فقط.
    return null;
  }
}

export function storeToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* تجاهل: الجلسة تبقى صالحة في الذاكرة حتى تحديث الصفحة. */
  }
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* تجاهل */
  }
}

export function login(email: string, password: string): Promise<TokenResponse> {
  return apiRequest<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export function fetchCurrentUser(
  token: string,
  signal?: AbortSignal,
): Promise<AuthUser> {
  return apiRequest<AuthUser>("/api/auth/me", { token, signal });
}

export function logout(token: string): Promise<LogoutResponse> {
  return apiRequest<LogoutResponse>("/api/auth/logout", {
    method: "POST",
    token,
  });
}

/* ---------------------------------------------------------------------------
   تحقق أوّلي في الواجهة — قبل إرسال الطلب
   يوفّر على المستخدم رحلة شبكة لخطأ ظاهر، ولا يحلّ محلّ تحقق السيرفر.
   --------------------------------------------------------------------------- */

/** الشكل نفسه الذي يفحصه `validate_email_shape` في الـBackend. */
export function validateEmail(value: string): string | null {
  const cleaned = value.trim();
  if (!cleaned) return "أدخل البريد الإلكتروني.";
  const [local, separator, domain] = splitEmail(cleaned);
  if (!separator || !local || !domain.includes(".") || domain.startsWith(".")) {
    return "صيغة البريد الإلكتروني غير صحيحة. مثال: name@entity.gov.sa";
  }
  return null;
}

export function validatePassword(value: string): string | null {
  if (!value.trim()) return "أدخل كلمة المرور.";
  return null;
}

function splitEmail(value: string): [string, string, string] {
  const index = value.indexOf("@");
  if (index === -1) return [value, "", ""];
  return [value.slice(0, index), "@", value.slice(index + 1)];
}
