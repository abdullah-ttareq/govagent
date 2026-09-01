/**
 * تخزين الإضافة المحلي — غلاف رفيع حول `chrome.storage.local`.
 *
 * **ما يُحفظ:** رمز الدخول ووقت انتهائه، بيانات الحساب للعرض، بصمة هذا
 * الجهاز، وعلامة أن شاشة الترحيب رُئيت. لا شيء غير ذلك.
 *
 * **ما لا يُحفظ ولم يعد له وجود:** `apiBaseUrl`. كان الإصدار السابق يخزّن
 * رابط سيرفر يضبطه الموظف بنفسه؛ حُذف مع حذف شاشة الإعدادات كلها — العنوان
 * صار ثابتًا وقت البناء في `config.js`. أي مفتاح `apiBaseUrl` باقٍ من
 * تثبيت قديم **يُمسح** عند أول تشغيل، فلا تبقى قيمة لا يقرؤها أحد.
 *
 * **ولا يُحفظ أي نصّ محادثة**: هذه الإضافة لم تعد واجهة محادثة أصلًا.
 *
 * كل دالة هنا تبتلع فشل التخزين وتعيد قيمة محايدة: نافذة لا تُفتح لأن
 * القراءة فشلت أسوأ من نافذة تبدأ من الترحيب.
 */

const KEYS = {
  token: "accessToken",
  refreshToken: "refreshToken",
  expiresAt: "tokenExpiresAt",
  account: "account",
  deviceId: "deviceId",
  deviceName: "deviceName",
  welcomeSeen: "welcomeSeen",
  installToken: "installToken",
  installTokenExpiresAt: "installTokenExpiresAt",
  runtimePort: "runtimePort",
};

/** مفاتيح إصدارات سابقة لم يعد لها معنى، تُمسح عند الإقلاع. */
const LEGACY_KEYS = ["apiBaseUrl", "conversationId", "user"];

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

/**
 * يمسح مفاتيح الإصدارات السابقة.
 *
 * أهمّها `apiBaseUrl`: تركه يعني بقاء عنوان سيرفر قديم على جهاز المستخدم
 * بلا أي شاشة تعرضه أو تغيّره — بيانات ميتة في أحسن الأحوال.
 */
export async function pruneLegacyKeys() {
  await remove(LEGACY_KEYS);
}

/* -------------------------------------------------------------------------
   الجلسة
   ------------------------------------------------------------------------- */

/**
 * @typedef {object} Session
 * @property {string} token رمز Supabase.
 * @property {number} expiresAt لحظة الانتهاء بالمللي ثانية منذ الحقبة.
 * @property {object|null} account ملف العمل كما أعاده `/api/account/login`.
 */

/** يعيد الجلسة المحفوظة، أو `null` إن لم يكن هناك رمز. */
export async function getSession() {
  const stored = await read([KEYS.token, KEYS.expiresAt, KEYS.account]);
  const token = stored[KEYS.token];
  if (!token) return null;
  return {
    token,
    expiresAt: stored[KEYS.expiresAt] ?? 0,
    account: stored[KEYS.account] ?? null,
  };
}

/** هل الجلسة موجودة ولم تنتهِ مدتها بعد؟ */
export function isSessionUsable(session, now = Date.now()) {
  return Boolean(session?.token) && session.expiresAt > now;
}

/**
 * يحفظ الجلسة بعد دخول ناجح.
 *
 * `expiresIn` مدة بالثواني تُحوَّل هنا إلى **لحظة انتهاء** مطلقة: مدة
 * متبقية محفوظة كما هي تصير خاطئة بمجرد إغلاق النافذة.
 */
export async function setSession({
  accessToken,
  refreshToken,
  expiresIn,
  account,
}) {
  await write({
    [KEYS.token]: accessToken,
    [KEYS.refreshToken]: refreshToken ?? "",
    [KEYS.expiresAt]: Date.now() + Math.max(0, expiresIn) * 1000,
    [KEYS.account]: account ?? null,
  });
}

/** يحدّث ملف العمل وحده بلا لمس الرمز. */
export async function updateAccount(account) {
  await write({ [KEYS.account]: account ?? null });
}

/**
 * يمسح الجلسة.
 *
 * **بصمة الجهاز تبقى عمدًا:** هي صفة للجهاز لا للمستخدم، وتغييرها عند كل
 * خروج يجعل الجهاز نفسه يبدو جهازًا جديدًا في كل مرة، فيصطدم المستخدم
 * برسالة «مفعّل على جهاز آخر» على جهازه هو.
 */
export async function clearSession() {
  await remove([KEYS.token, KEYS.refreshToken, KEYS.expiresAt, KEYS.account]);
  // رمز التركيب يخصّ جلسةً بعينها: تركه بعد الخروج يترك سرًّا صالحًا على
  // جهاز قد يستعمله غير صاحبه.
  await clearInstallToken();
}

/* -------------------------------------------------------------------------
   رمز التركيب — لمرة واحدة، ولدقائق التركيب وحدها
   ------------------------------------------------------------------------- */

/**
 * ⚠️ **أقصر ما يُحفظ في هذه الإضافة عمرًا.**
 *
 * يُحفظ لأن نافذة الإضافة تُغلق بمجرد أن يفقدها المستخدم التركيز — وهو ما
 * يحدث حتمًا حين يفتح المثبّت — فلو بقي في الذاكرة وحدها لضاع في منتصف
 * التركيب. ويُمحى فور نجاح التفعيل أو فشله أو انتهاء صلاحيته.
 */
export async function setInstallToken(token, expiresAt) {
  await write({
    [KEYS.installToken]: token,
    [KEYS.installTokenExpiresAt]: expiresAt,
  });
}

/** يعيد الرمز إن كان موجودًا **وصالحًا**، أو `null`. */
export async function getInstallToken() {
  const stored = await read([KEYS.installToken, KEYS.installTokenExpiresAt]);
  const token = stored[KEYS.installToken];
  if (!token) return null;

  const expiresAt = Date.parse(stored[KEYS.installTokenExpiresAt] ?? "");
  if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) {
    // منتهٍ: يُمحى بدل أن يُرسل فيُرفض.
    await clearInstallToken();
    return null;
  }
  return token;
}

export async function clearInstallToken() {
  await remove([KEYS.installToken, KEYS.installTokenExpiresAt]);
}

/* -------------------------------------------------------------------------
   منفذ الـRuntime المكتشَف
   ------------------------------------------------------------------------- */

/** يُحفظ ليُفتح GovMind مباشرة في الزيارات التالية بلا استطلاع كل المنافذ. */
export async function setRuntimePort(port) {
  await write({ [KEYS.runtimePort]: port });
}

export async function getRuntimePort() {
  const stored = await read(KEYS.runtimePort);
  const value = stored[KEYS.runtimePort];
  return Number.isInteger(value) ? value : null;
}

/* -------------------------------------------------------------------------
   الجهاز
   ------------------------------------------------------------------------- */

/** يعيد بصمة الجهاز المحفوظة، أو `null`. */
export async function getDeviceId() {
  const stored = await read(KEYS.deviceId);
  const value = stored[KEYS.deviceId];
  return typeof value === "string" && value.length >= 8 ? value : null;
}

export async function setDeviceId(deviceId) {
  await write({ [KEYS.deviceId]: deviceId });
}

export async function getDeviceName() {
  const stored = await read(KEYS.deviceName);
  const value = stored[KEYS.deviceName];
  return typeof value === "string" && value.trim() ? value : null;
}

export async function setDeviceName(name) {
  await write({ [KEYS.deviceName]: name });
}

/* -------------------------------------------------------------------------
   شاشة الترحيب
   ------------------------------------------------------------------------- */

export async function getWelcomeSeen() {
  const stored = await read(KEYS.welcomeSeen);
  return stored[KEYS.welcomeSeen] === true;
}

export async function setWelcomeSeen() {
  await write({ [KEYS.welcomeSeen]: true });
}
