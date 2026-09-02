/**
 * عميل GovMind Runtime — **من الأصل نفسه، وبلا أي عنوان مكتوب**.
 *
 * ⚠️ **لا يوجد في هذا الملف — ولا يجوز أن يوجد — `http://127.0.0.1:8000`
 * ولا أي عنوان لخدمة سحابية.** الصفحة يخدمها الـRuntime على الاسترجاع
 * المحلي، والمسارات هنا نسبية، فتذهب إلى المنفذ الذي حجزه هو أيًّا كان.
 * كتابةُ عنوان الـControl Plane هنا كانت ستضع الـBackend في متناول كل
 * سكربت في المتصفح، وتجعل بيان اعتماد الجهاز عديم الفائدة.
 *
 * **من يتحدث إلى الـControl Plane؟ الـRuntime وحده**، بقائمة مسارات بيضاء
 * صريحة (`control_plane.ALLOWED_ROUTES`)، ويلصق بيان اعتماد الجهاز في
 * جانب الخادم. **لا تستقبل هذه الصفحة بيان الاعتماد ولا تراه ولا تخزّنه.**
 *
 * **رمز الجلسة المحلي** الذي تستعمله الدوال هنا ليس بيان اعتماد الجهاز:
 * قيمة تُولَّد عند كل إقلاع للـRuntime وتموت بانتهائه، ووظيفتها أن تثبت
 * أن الطلب من الصفحة التي خدمها الـRuntime لا من موقع فتحه المستخدم في
 * تبويب آخر.
 */

/** حالة ربط الجهاز كما يعيدها `GET /api/app/session` من الـRuntime. */
export type RuntimeSession = {
  service: "govmind-runtime";
  /** هل تمّ استبدال جلسة التركيب فصار الجهاز مربوطًا بالحساب؟ */
  linked: boolean;
  phase: string;
  message: string;
  progress: number | null;
  downloaded_bytes: number;
  total_bytes: number;
  device_name: string | null;
  subscription_status: string | null;
  subscription_expires_at: string | null;
  account_email: string | null;
  is_ready: boolean;
  needs_activation: boolean;
  /**
   * هل تُعالَج المحادثة خارج هذا الجهاز؟
   *
   * ⚠️ **تصل قبل أول رسالة عمدًا.** الواجهة تقول للمستخدم أين سيُعالَج
   * نصّه قبل أن يكتبه، لا بعد أن أرسله. اختيارية لأن نسخة Runtime أقدم
   * لا ترسلها، وغيابُها يُقرأ «محلي» — الافتراض الأحفظ.
   */
  cloud_mode?: boolean;
};

/** دور واحد من سياق المحادثة كما يُرسل إلى الـRuntime. */
export type ChatTurnIn = { role: "user" | "assistant"; content: string };

/** ردّ محادثة واحد، **ومعه أين عولج**. */
export type ChatReply = {
  reply: string;
  /** اسم المحرّك أو المزوّد الذي أجاب — للعرض، لا سرّ فيه. */
  engine?: string;
  /** هل غادر النصّ الجهاز فعلًا؟ **من الـRuntime لا من تخمين الواجهة.** */
  cloud?: boolean;
};

/** فشلٌ برسالة عربية جاهزة للعرض. لا نصّ استثناء خام يصل المستخدم. */
export class RuntimeError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "RuntimeError";
    this.status = status;
  }
}

export const RUNTIME_OFFLINE_MESSAGE =
  "تعذّر الاتصال بخدمة GovMind على هذا الجهاز. أغلق GovMind ثم افتحه من " +
  "اختصاره مرة أخرى.";

const SESSION_HEADER = "X-GovMind-Session";

/**
 * رمز الجلسة المحلي، مقروءًا مرة واحدة ومحفوظًا في الذاكرة.
 *
 * **في الذاكرة لا في `localStorage`:** الرمز يتغيّر عند كل إقلاع للـRuntime،
 * ونسخةٌ محفوظة من إقلاع سابق تُرفض بـ401 فتبدو الصفحة معطوبة. والذاكرة
 * تموت مع التبويب كما يموت الرمز مع الخدمة.
 */
let cachedToken: string | null = null;

async function readSessionToken(force = false): Promise<string> {
  if (cachedToken && !force) return cachedToken;

  let response: Response;
  try {
    response = await fetch("/api/local/session", { cache: "no-store" });
  } catch {
    throw new RuntimeError(RUNTIME_OFFLINE_MESSAGE);
  }
  if (!response.ok) {
    throw new RuntimeError(RUNTIME_OFFLINE_MESSAGE, response.status);
  }

  const payload = (await response.json()) as { token?: string };
  const token = payload.token?.trim();
  if (!token) throw new RuntimeError(RUNTIME_OFFLINE_MESSAGE);

  cachedToken = token;
  return token;
}

async function request<T>(
  path: string,
  { method = "GET", body }: { method?: "GET" | "POST" | "DELETE"; body?: unknown } = {},
  { retried = false }: { retried?: boolean } = {},
): Promise<T> {
  const token = await readSessionToken(retried);

  const headers: Record<string, string> = { [SESSION_HEADER]: token };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new RuntimeError(RUNTIME_OFFLINE_MESSAGE);
  }

  // 401 يعني غالبًا أن الـRuntime أُعيد تشغيله فتغيّر رمزه. تُقرأ القيمة
  // الجديدة **مرة واحدة** ثم يُعاد الطلب؛ ولا تكرار بلا نهاية.
  if (response.status === 401 && !retried) {
    cachedToken = null;
    return request<T>(path, { method, body }, { retried: true });
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const detail = (payload as { detail?: string } | null)?.detail?.trim();
    throw new RuntimeError(
      detail || "تعذّر إتمام العملية. أعد المحاولة.",
      response.status,
    );
  }

  return payload as T;
}

/** يقرأ حالة الربط والتجهيز. **لا يطلب بريدًا ولا كلمة مرور.** */
export function fetchSession(): Promise<RuntimeSession> {
  return request<RuntimeSession>("/api/app/session");
}

/** «إعادة التحقق»: يعيد الـRuntime فحص الربط الآن ويردّ بالنتيجة. */
export function recheckSession(): Promise<RuntimeSession> {
  return request<RuntimeSession>("/api/app/recheck", { method: "POST" });
}

/**
 * يرسل رسالة وسياق المحادثة إلى الـRuntime المحلي.
 *
 * ⚠️ **الوجهة من هنا هي الـRuntime وحده، دائمًا.** المسار نسبي ويذهب إلى
 * الأصل الذي خدم هذه الصفحة — لا عنوان خدمة سحابية في هذا الملف ولا في
 * حزمة الواجهة كلها.
 *
 * ⚠️ **ولا تحمل هذه الطلبات بيان اعتماد الجهاز.** الـRuntime يضيفه في
 * جانب الخادم حين يمرّر الطلب. وضعُه هنا يعني تسليمه لكل سكربت في
 * المتصفح ولكل من يفتح أدوات المطوّر.
 *
 * **أين يُعالَج النصّ؟** يقرّره الـRuntime، ويقوله الردّ في ``cloud``.
 * الواجهة تعرض ما يصلها ولا تدّعي محليّة من عندها.
 */
export function sendMessage(
  message: string,
  history: ChatTurnIn[] = [],
  conversationId?: string,
): Promise<ChatReply> {
  return request<ChatReply>("/api/app/chat", {
    method: "POST",
    body: { message, history, conversation_id: conversationId ?? null },
  });
}

/** ملخّص محادثة كما يعرضه الشريط الجانبي — بلا نصوص الرسائل. */
export type ConversationSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
};

/** محادثة كاملة برسائلها. */
export type Conversation = ConversationSummary & {
  messages: { role: "user" | "assistant"; content: string; created_at: string }[];
};

/**
 * المحادثات المحفوظة — **في تخزين يملكه الـRuntime، لا في المتصفح**.
 *
 * ⚠️ لا يمرّر أي طلب هنا بريدًا ولا معرّف حساب: الـRuntime يعرف الحساب
 * المرتبط حاليًا ويفصل به. لو أرسلته الصفحة، لصار تبديل حرف فيه بابًا
 * لقراءة محادثات حساب آخر على الجهاز نفسه.
 */
export function listConversations(): Promise<{
  conversations: ConversationSummary[];
}> {
  return request("/api/app/conversations");
}

export function createConversation(): Promise<Conversation> {
  return request("/api/app/conversations", { method: "POST" });
}

export function fetchConversation(id: string): Promise<Conversation> {
  return request(`/api/app/conversations/${encodeURIComponent(id)}`);
}

export function deleteConversation(id: string): Promise<{ deleted: boolean }> {
  return request(`/api/app/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/** يحوّل البايتات إلى نصّ عربي مقروء — لشريط تقدّم تنزيل المودل. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} ك.ب`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} م.ب`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} ج.ب`;
}

/** حالة الاشتراك بالعربية. **بلا أي ذكر لجهة أو دور.** */
export const SUBSCRIPTION_LABELS: Record<string, string> = {
  trial: "فترة تجريبية",
  active: "فعّال",
  expired: "منتهٍ",
  suspended: "موقوف",
  cancelled: "ملغى",
};
