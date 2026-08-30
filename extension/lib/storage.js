/**
 * تخزين الإضافة المحلي — غلاف رفيع حول `chrome.storage.local`.
 *
 * **رمز الدخول يُحفظ هنا وحده**، لا في `localStorage` ولا في أي مكان آخر:
 * تخزين الإضافة معزول عن كل صفحة يفتحها الموظف، فلا تصل إليه سكربتات
 * المواقع. الإضافة لا تقرأ أي صفحة أصلًا ولا تملك صلاحية لذلك.
 *
 * كل دالة هنا تبتلع فشل التخزين وتعيد قيمة محايدة: نافذة لا تُفتح لأن
 * القراءة من التخزين فشلت أسوأ من نافذة تبدأ فارغة.
 */

export const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** مفاتيح التخزين. `apiBaseUrl` بالاسم نفسه الذي استخدمه الـStarter. */
const KEYS = {
  baseUrl: "apiBaseUrl",
  token: "accessToken",
  expiresAt: "tokenExpiresAt",
  user: "user",
  conversationId: "conversationId",
};

async function read(keys) {
  try {
    return await chrome.storage.local.get(keys);
  } catch {
    return {};
  }
}

async function write(values) {
  try {
    await chrome.storage.local.set(values);
  } catch {
    /* تجاهل: الجلسة تبقى صالحة في الذاكرة حتى تُغلق النافذة. */
  }
}

async function remove(keys) {
  try {
    await chrome.storage.local.remove(keys);
  } catch {
    /* تجاهل */
  }
}

/* -------------------------------------------------------------------------
   رابط السيرفر
   ------------------------------------------------------------------------- */

/** يعيد الرابط المحفوظ، أو الافتراضي إن لم يُحفظ شيء. */
export async function getApiBaseUrl() {
  const stored = await read(KEYS.baseUrl);
  return stored[KEYS.baseUrl] || DEFAULT_API_BASE_URL;
}

export async function setApiBaseUrl(baseUrl) {
  await write({ [KEYS.baseUrl]: baseUrl });
}

/* -------------------------------------------------------------------------
   الجلسة
   ------------------------------------------------------------------------- */

/**
 * @typedef {object} Session
 * @property {string} token رمز الدخول.
 * @property {number} expiresAt وقت الانتهاء بالمللي ثانية منذ الحقبة.
 * @property {object|null} user بيانات الموظف كما أعادها `/api/auth/login`.
 */

/** يعيد الجلسة المحفوظة، أو `null` إن لم يكن هناك رمز. */
export async function getSession() {
  const stored = await read([KEYS.token, KEYS.expiresAt, KEYS.user]);
  const token = stored[KEYS.token];
  if (!token) return null;
  return {
    token,
    expiresAt: stored[KEYS.expiresAt] ?? 0,
    user: stored[KEYS.user] ?? null,
  };
}

/**
 * يحفظ الجلسة بعد تسجيل دخول ناجح.
 *
 * `expires_in` مدة بالثواني، وتُحوَّل هنا إلى **لحظة انتهاء** مطلقة: مدة
 * متبقية محفوظة كما هي تصير خاطئة بمجرد إغلاق النافذة.
 */
export async function setSession({ accessToken, expiresIn, user }) {
  await write({
    [KEYS.token]: accessToken,
    [KEYS.expiresAt]: Date.now() + Math.max(0, expiresIn) * 1000,
    [KEYS.user]: user ?? null,
  });
}

/** يحدّث بيانات الموظف وحدها (بعد `/api/auth/me`) بلا لمس الرمز. */
export async function updateSessionUser(user) {
  await write({ [KEYS.user]: user ?? null });
}

/**
 * يمسح الجلسة **والمحادثة معها**.
 *
 * المحادثة ملك صاحب الرمز، فتركها بعد الخروج يعرضها على من يسجّل الدخول
 * بعده على الجهاز نفسه.
 */
export async function clearSession() {
  await remove([KEYS.token, KEYS.expiresAt, KEYS.user, KEYS.conversationId]);
}

/* -------------------------------------------------------------------------
   آخر محادثة
   ------------------------------------------------------------------------- */

/** معرّف آخر محادثة، أو `null`. */
export async function getConversationId() {
  const stored = await read(KEYS.conversationId);
  const value = stored[KEYS.conversationId];
  return typeof value === "number" && value > 0 ? value : null;
}

export async function setConversationId(conversationId) {
  await write({ [KEYS.conversationId]: conversationId });
}

export async function clearConversationId() {
  await remove(KEYS.conversationId);
}
