/**
 * عميل GovMind Backend داخل الإضافة.
 *
 * كل المسارات هنا موجودة فعلًا في الـBackend ولا يُخترع منها شيء:
 * `POST /api/auth/login` و `GET /api/auth/me` و `POST /api/auth/logout`
 * (`backend/app/api/auth.py`)، و `POST /api/chat` (`backend/app/api/chat.py`)،
 * و `GET /api/conversations/{id}/messages` (`backend/app/api/conversations.py`).
 *
 * رابط السيرفر يُقرأ من التخزين **عند كل طلب** لا مرة واحدة: الموظف قد
 * يغيّره من الإعدادات والنافذة مفتوحة.
 */

import { getApiBaseUrl } from "./storage.js";

/** رسالة موحّدة لتوقّف السيرفر أو انقطاع الشبكة. */
export const OFFLINE_MESSAGE =
  "تعذّر الاتصال بسيرفر جهتك. تأكد من تشغيل السيرفر ومن صحة رابطه في الإعدادات.";

/** خطأ يحمل رمز الحالة ومعرّف الخطأ النصّي من غلاف أخطاء الـBackend. */
export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** لم يصل الطلب إلى السيرفر أصلًا، فلا رمز حالة له. */
export class NetworkError extends Error {
  constructor(message = OFFLINE_MESSAGE) {
    super(message);
    this.name = "NetworkError";
  }
}

/**
 * إذن الاتصال بنطاق السيرفر غير ممنوح للإضافة.
 *
 * يُكتشف **قبل** إرسال الطلب: بلا هذا الفحص يفشل `fetch` بالخطأ نفسه الذي
 * يعطيه سيرفر متوقف، فيُرسل الموظف يبحث عن عطل في سيرفر يعمل.
 */
export class HostPermissionError extends Error {
  constructor(origin) {
    super(
      "لم تمنح المتصفحَ إذنَ الاتصال بنطاق سيرفر جهتك، فلا تستطيع الإضافة " +
        "إرسال أي طلب إليه.",
    );
    this.name = "HostPermissionError";
    this.origin = origin;
  }
}

/** نمط الأصل كما تفهمه صلاحيات الإضافة: `http://host:port/*`. */
export function originPattern(baseUrl) {
  return new URL(baseUrl).origin + "/*";
}

/** هل مُنحت الإضافة إذن الاتصال بهذا الرابط؟ */
export async function hasHostPermission(baseUrl) {
  try {
    return await chrome.permissions.contains({
      origins: [originPattern(baseUrl)],
    });
  } catch {
    // رابط لا يصلح نمطًا (لا يقع تحت http/https) — يُعامل كغير مسموح.
    return false;
  }
}

/**
 * يطلب إذن الاتصال بالنطاق. **يجب أن يُستدعى من داخل نقرة المستخدم**،
 * وإلا رفضه المتصفح بلا أن يعرض شيئًا.
 */
export async function requestHostPermission(baseUrl) {
  try {
    return await chrome.permissions.request({
      origins: [originPattern(baseUrl)],
    });
  } catch {
    return false;
  }
}

/**
 * ينفّذ طلبًا ويعيد جسم الرد مُحلّلًا.
 *
 * كل فشل يخرج من هنا كـ`HostPermissionError` أو `NetworkError` أو
 * `ApiError` برسالة عربية جاهزة للعرض — لا يصل الموظف نصّ استثناء خام.
 */
export async function apiRequest(path, { method = "GET", body, token } = {}) {
  const baseUrl = await getApiBaseUrl();

  if (!(await hasHostPermission(baseUrl))) {
    throw new HostPermissionError(originPattern(baseUrl));
  }

  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new NetworkError(
      `تعذّر الاتصال بـ${baseUrl}. تأكد من تشغيل سيرفر جهتك ومن صحة الرابط في الإعدادات.`,
    );
  }

  if (response.status === 204) return undefined;

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const error = payload ?? {};
    throw new ApiError(
      (error.detail ?? "").trim() || "حدث خطأ غير متوقع. حاول مرة أخرى.",
      response.status,
      error.code ?? "unknown_error",
    );
  }

  return payload;
}

/* -------------------------------------------------------------------------
   المصادقة
   ------------------------------------------------------------------------- */

/** `POST /api/auth/login` — يعيد `TokenResponse`. */
export function login(email, password) {
  return apiRequest("/api/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

/** `GET /api/auth/me` — يعيد `UserOut`. يعمل ولو انتهى اشتراك الجهة. */
export function fetchCurrentUser(token) {
  return apiRequest("/api/auth/me", { token });
}

/** `POST /api/auth/logout` — تأكيد فقط؛ الرمز موقّع ولا يُلغى على السيرفر. */
export function logout(token) {
  return apiRequest("/api/auth/logout", { method: "POST", token });
}

/* -------------------------------------------------------------------------
   المحادثة
   ------------------------------------------------------------------------- */

/**
 * `POST /api/chat` — يعيد `ChatResponse`.
 *
 * **لا يُرسل حقل `history`:** مع رمز الدخول يقرأ الـBackend السياق من
 * المحادثة المحفوظة، وإرسال سياق من العميل يُرفض بـ422 لأنه قابل للتلفيق.
 * `conversationId` فارغًا يفتح محادثة جديدة ويعيد معرّفها في الرد.
 */
export function sendChatMessage(token, message, conversationId) {
  return apiRequest("/api/chat", {
    method: "POST",
    token,
    body: {
      message,
      ...(conversationId ? { conversation_id: conversationId } : {}),
    },
  });
}

/** `GET /api/conversations/{id}/messages` — من الأقدم إلى الأحدث. */
export function listMessages(token, conversationId) {
  return apiRequest(`/api/conversations/${conversationId}/messages`, { token });
}
