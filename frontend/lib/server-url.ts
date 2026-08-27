/**
 * رابط سيرفر الجهة — يُضبط من صفحة الإعدادات ويُحفظ في المتصفح.
 *
 * **لماذا لا يكفي `NEXT_PUBLIC_BACKEND_URL`؟** متغيّرات `NEXT_PUBLIC_` تُدمج
 * في الحزمة وقت البناء، فقيمة واحدة لكل نسخة مبنيّة. الجهة تنشر النظام على
 * سيرفرها هي، والموظف يحتاج ضبط العنوان بلا إعادة بناء — لذلك القيمة
 * المخزّنة محليًا تسبق قيمة البناء، وقيمة البناء تبقى الافتراضي.
 */

const STORAGE_KEY = "govagent.server_url";

/** الافتراضي وقت البناء — يُستخدم ما لم يحفظ الموظف عنوانًا. */
export const DEFAULT_SERVER_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL?.trim() || "http://localhost:8000";

/** حدث يُطلَق عند تغيّر العنوان، لتتابعه الواجهة في التبويب نفسه. */
const CHANGE_EVENT = "govagent:server-url-changed";

/** يزيل الفراغ والشرطة الأخيرة، فلا يتكوّن `//api/...` عند التركيب. */
export function normalizeServerUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

/**
 * يفحص العنوان قبل حفظه. يعيد رسالة عربية عند الخطأ، و`null` عند القبول.
 */
export function validateServerUrl(value: string): string | null {
  const cleaned = normalizeServerUrl(value);
  if (!cleaned) return "أدخل عنوان سيرفر الجهة.";

  let parsed: URL;
  try {
    parsed = new URL(cleaned);
  } catch {
    return "العنوان غير صالح. اكتبه كاملًا مع البروتوكول، مثل: http://10.0.0.5:8000";
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return "العنوان يجب أن يبدأ بـhttp:// أو https://";
  }
  if (parsed.search || parsed.hash) {
    return "العنوان يجب أن يكون عنوان السيرفر وحده، بلا مسار استعلام ولا وسم.";
  }
  return null;
}

/** العنوان المستخدَم في كل الطلبات الآن. */
export function getServerUrl(): string {
  if (typeof window === "undefined") return DEFAULT_SERVER_URL;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored ? normalizeServerUrl(stored) : DEFAULT_SERVER_URL;
  } catch {
    return DEFAULT_SERVER_URL;
  }
}

/** هل العنوان الحالي محفوظ من الموظف، أم هو افتراضي البناء؟ */
export function hasStoredServerUrl(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== null;
  } catch {
    return false;
  }
}

export function storeServerUrl(value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, normalizeServerUrl(value));
  } catch {
    /* تجاهل: التخزين قد يكون ممنوعًا في وضع التصفح الخاص. */
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** يعيد العنوان إلى افتراضي البناء. */
export function resetServerUrl(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* تجاهل */
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** يشترك في تغيّر العنوان — من هذا التبويب أو من تبويب آخر. */
export function subscribeToServerUrl(listener: () => void): () => void {
  if (typeof window === "undefined") return () => {};

  // `storage` لا يُطلَق في التبويب الذي كتب القيمة، لذلك حدثنا الخاص معه.
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

/** فحص الاتصال: `/health` هو المسار الوحيد الذي يعمل بلا رمز دخول. */
export type HealthResponse = {
  status: string;
  app_env: string;
  model_provider: string;
  oracle: { configured: boolean; status: string; detail: string | null };
};
