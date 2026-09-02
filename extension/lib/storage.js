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
  installStage: "installStage",
  downloadId: "downloadId",
  downloadFileName: "downloadFileName",
  planAckFor: "planAckFor",
  installOwner: "installOwner",
};

/**
 * مفاتيح إصدارات سابقة لم يعد لها معنى، تُمسح عند الإقلاع.
 *
 * ⚠️ **المجموعة الثانية خلّفتها نسخة معطوبة**: كانت تحفظ مرحلة «تفعيل»
 * أو «انتظار Runtime» بأسماء مفاتيح لم تعد مستعملة. بقاؤها كان يعيد
 * النافذة إلى شاشة تقدّم عن عملية لا وجود لها.
 */
const LEGACY_KEYS = [
  "apiBaseUrl",
  "conversationId",
  "user",
  "activating",
  "awaitingRuntime",
  "awaiting_runtime",
  "runtimeActivating",
  "installState",
  "onboardingStep",
];

/** قيم `installStage` التي خلّفتها نسخ سابقة ولم تعد صالحة. */
const LEGACY_STAGES = new Set([
  "activating",
  "awaiting_runtime",
  "awaitingRuntime",
  "awaiting-runtime",
  "handing_over",
]);

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
  // ومرحلة التثبيت تخصّ حسابًا بعينه كذلك — ومعها اسم مالكها، فلا يرث
  // الحسابُ التالي على هذا الجهاز شيئًا من سابقه.
  await clearInstallProgress();
  await remove([KEYS.installOwner]);

  // ⚠️ **`planAckFor` يبقى عمدًا.** هو بريد من أقرّ طريقة البدء، لا علامة
  // عامة. مسحه كان يعيد عرض شاشة الخطة على صاحبه في كل مرة يعود فيها،
  // وتركُه لا يسرّب شيئًا إلى غيره: المقارنة بالبريد الحالي، فمن يدخل
  // بحساب آخر يرى الشاشة كما يجب.
}

/* -------------------------------------------------------------------------
   مرحلة التثبيت — تُستأنف بعد إغلاق النافذة
   ------------------------------------------------------------------------- */

/**
 * ⚠️ **نافذة الإضافة تُغلق بمجرد أن تفقد التركيز** — وهو ما يحدث حتمًا حين
 * يفتح المستخدم المثبّت أو يوافق على نافذة ويندوز. فلو عاشت مرحلة التثبيت
 * في الذاكرة وحدها لعادت النافذة إلى «ابدأ التثبيت» بعد تنزيلٍ اكتمل،
 * فيبدأ المستخدم تنزيلًا ثانيًا ويُطلب رمز تركيب ثالث بلا داعٍ.
 *
 * المخزون **حقائق لا شاشات**: أين وصل التنزيل، وهل أعلن المستخدم أنه بدأ
 * التركيب. الشاشة تُشتقّ منها في `resolveStep`، فلا مصدرَي حقيقة يتخالفان.
 *
 * @typedef {"idle"|"downloading"|"downloaded"|"installing"} InstallStage
 */
const INSTALL_STAGES = ["idle", "downloading", "downloaded", "installing"];

export async function getInstallProgress() {
  const stored = await read([
    KEYS.installStage,
    KEYS.downloadId,
    KEYS.downloadFileName,
  ]);
  const stage = stored[KEYS.installStage];
  const downloadId = stored[KEYS.downloadId];
  return {
    stage: INSTALL_STAGES.includes(stage) ? stage : "idle",
    downloadId: Number.isInteger(downloadId) ? downloadId : null,
    fileName:
      typeof stored[KEYS.downloadFileName] === "string"
        ? stored[KEYS.downloadFileName]
        : null,
  };
}

/**
 * ينظّف حالة تثبيت لم تعد تعني شيئًا، **قبل أن تُرسم أي شاشة**.
 *
 * ⚠️ **هذا ما يمنع دوّامة الإقلاع.** حالةٌ خلّفتها نسخة معطوبة — «تفعيل»
 * أو «انتظار Runtime» بلا تنزيل ولا رمز — كانت تعيد النافذة إلى شاشة
 * تقدّمٍ عن عملية لم تبدأ قطّ، وتبقى تدور بلا شيء ينهيها.
 *
 * **ما يُمسح:**
 * 1. مرحلة بقيمة لم تعد في المفردات (`activating` وأخواتها).
 * 2. مرحلة متقدّمة بلا `downloadId` صالح — لا تنزيل يُستأنف عليه.
 * 3. مرحلة تخصّ حسابًا آخر على الجهاز نفسه.
 * 4. رمز تركيب انتهت صلاحيته (ومعه مرحلةُ «يُركّب» التي تعتمد عليه).
 *
 * **وما يبقى:** تنزيلٌ مكتمل صالح، وجلسةُ تركيبٍ سارية.
 *
 * @param {string|null} email بريد صاحب الجلسة الحالية.
 * @returns {Promise<string[]>} أسباب ما مُسح — للاختبارات وللتشخيص.
 */
export async function reconcileInstallState(email) {
  const reasons = [];
  const stored = await read([
    KEYS.installStage,
    KEYS.downloadId,
    KEYS.installOwner,
    KEYS.installToken,
  ]);

  const rawStage = stored[KEYS.installStage];
  const downloadId = stored[KEYS.downloadId];
  const owner = stored[KEYS.installOwner];
  const current = email ? String(email).toLowerCase() : null;

  if (rawStage === undefined && downloadId === undefined) {
    // لا حالة أصلًا؛ نثبّت المالك وننصرف.
    if (current) await write({ [KEYS.installOwner]: current });
    return reasons;
  }

  if (LEGACY_STAGES.has(rawStage)) reasons.push("legacy-stage");
  if (rawStage !== undefined && !INSTALL_STAGES.includes(rawStage)) {
    reasons.push("unknown-stage");
  }
  if (
    INSTALL_STAGES.includes(rawStage) &&
    rawStage !== "idle" &&
    !Number.isInteger(downloadId)
  ) {
    reasons.push("no-download-id");
  }
  if (owner && current && owner !== current) reasons.push("other-account");

  // رمز منتهٍ: `getInstallToken` يمسحه من تلقائه، وما يعنينا هنا أن مرحلة
  // «يُركّب» بلا رمز سارٍ لا شيء ينهيها، فتعود إلى تعليمات الفتح.
  if (rawStage === "installing" && stored[KEYS.installToken]) {
    const token = await getInstallToken();
    if (!token) reasons.push("expired-session");
  }

  if (reasons.length > 0) {
    await clearInstallProgress();
    await clearInstallToken();
  }
  if (current) await write({ [KEYS.installOwner]: current });

  return reasons;
}

export async function setInstallProgress({ stage, downloadId, fileName }) {
  const payload = {};
  if (stage !== undefined) {
    payload[KEYS.installStage] = INSTALL_STAGES.includes(stage) ? stage : "idle";
  }
  if (downloadId !== undefined) payload[KEYS.downloadId] = downloadId;
  if (fileName !== undefined) payload[KEYS.downloadFileName] = fileName;
  await write(payload);
}

export async function clearInstallProgress() {
  await remove([KEYS.installStage, KEYS.downloadId, KEYS.downloadFileName]);
}

/** بريد صاحب حالة التثبيت المحفوظة، أو `null`. للاختبارات والتشخيص. */
export async function getInstallOwner() {
  const stored = await read(KEYS.installOwner);
  const value = stored[KEYS.installOwner];
  return typeof value === "string" ? value : null;
}

/* -------------------------------------------------------------------------
   إقرار طريقة البدء — لكل حساب على حدة
   ------------------------------------------------------------------------- */

/**
 * هل أقرّ **هذا البريد** طريقة البدء؟
 *
 * ⚠️ **مقارنة ببريد الحساب لا علامة عامة.** حاسبٌ يتناوب عليه اثنان: من
 * أقرّ لا يُسأل مرة أخرى، ومن لم يقرّ يُسأل ولو أقرّ زميله على الجهاز نفسه.
 */
export async function hasAcknowledgedPlan(email) {
  if (!email) return false;
  const stored = await read(KEYS.planAckFor);
  const value = stored[KEYS.planAckFor];
  return typeof value === "string" && value === String(email).toLowerCase();
}

export async function acknowledgePlan(email) {
  if (!email) return;
  await write({ [KEYS.planAckFor]: String(email).toLowerCase() });
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
