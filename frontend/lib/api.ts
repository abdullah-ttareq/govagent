/**
 * عميل بسيط للاتصال بـGovAgent Backend.
 *
 * رابط السيرفر يُقرأ من `lib/server-url.ts` **عند كل طلب** لا مرة واحدة عند
 * تحميل الوحدة: الموظف قد يغيّره من صفحة الإعدادات أثناء الجلسة، وقيمة
 * مُثبَّتة في ثابت وحدة تبقى القديمة حتى تحديث الصفحة.
 */

import { getServerUrl } from "@/lib/server-url";

/** رسالة موحّدة لانقطاع الشبكة أو توقّف السيرفر. */
export const OFFLINE_MESSAGE =
  "تعذّر الاتصال بسيرفر جهتك. تأكد من تشغيل السيرفر ومن صحة رابطه في الإعدادات.";

/**
 * غلاف الخطأ الموحّد الذي يعيده الـBackend من `api/errors.py`:
 * `{ detail, status, code, errors }`.
 */
export type ApiErrorPayload = {
  detail?: string;
  status?: number;
  code?: string;
  errors?: { field?: string; message?: string }[];
};

/** خطأ يحمل رمز الحالة ومعرّف الخطأ النصّي، ليبني عليه العميل منطقه. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** انقطاع الاتصال — لم يصل الطلب إلى السيرفر أصلًا، فلا رمز حالة له. */
export class NetworkError extends Error {
  constructor(message: string = OFFLINE_MESSAGE) {
    super(message);
    this.name = "NetworkError";
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** رمز الدخول. يُرسل في ترويسة Authorization: Bearer <token>. */
  token?: string | null;
  signal?: AbortSignal;
};

/**
 * ينفّذ طلبًا على الـBackend ويعيد جسم الرد مُحلّلًا.
 *
 * كل فشل يخرج من هنا كـ`NetworkError` أو `ApiError` برسالة عربية جاهزة
 * للعرض — لا يصل المستخدم نصّ استثناء خام ولا شاشة بيضاء.
 */
export async function apiRequest<T>(
  path: string,
  { method = "GET", body, token, signal }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${getServerUrl()}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (caught) {
    // إلغاء الطلب ليس خطأ شبكة — يُمرَّر كما هو ليتجاهله المُستدعي.
    if (caught instanceof DOMException && caught.name === "AbortError") throw caught;
    throw new NetworkError();
  }

  if (response.status === 204) return undefined as T;

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const error = (payload ?? {}) as ApiErrorPayload;
    throw new ApiError(
      error.detail?.trim() || "حدث خطأ غير متوقع. حاول مرة أخرى.",
      response.status,
      error.code ?? "unknown_error",
    );
  }

  return payload as T;
}

/** مقطع ملف استُند إليه في الرد — يطابق `ChatSource` في الـBackend. */
export type ChatSource = {
  file_id: number;
  file_name: string;
  chunk_index: number;
  score: number;
};

export type ChatResponse = {
  reply: string;
  provider: string;
  sources: ChatSource[];
  /** المحادثة التي حُفظ فيها التبادل. فارغ في الطلبات بلا رمز دخول. */
  conversation_id: number | null;
};

/**
 * يرسل رسالة إلى الإيجنت.
 *
 * **لا يُرسل `history`:** مع رمز الدخول يقرأ الـBackend السياق من المحادثة
 * المحفوظة، وإرسال سياق من المتصفح يُرفض بـ422 لأنه قابل للتلفيق.
 * `conversationId` فارغًا يفتح محادثة جديدة ويعيد معرّفها في الرد.
 */
export async function sendChatMessage(
  message: string,
  token?: string | null,
  conversationId?: number | null,
): Promise<ChatResponse> {
  return apiRequest<ChatResponse>("/api/chat", {
    method: "POST",
    body: {
      message,
      ...(conversationId ? { conversation_id: conversationId } : {}),
    },
    token,
  });
}
