/**
 * عميل GovMind Backend داخل الإضافة.
 *
 * كل المسارات هنا موجودة فعلًا في `backend/app/api/entitlements.py`:
 * `POST /api/account/login`، و `GET /api/account/subscription`،
 * و `POST /api/account/devices/activate`، و `POST /api/account/devices/verify`،
 * و `POST /api/account/installer/download-url`.
 *
 * **العنوان ثابت من `config.js` ولا يُقرأ من التخزين.** الإصدار السابق كان
 * يقرأ رابطًا يضبطه الموظف عند كل طلب؛ لم يعد لذلك وجود — لا شاشة إعدادات
 * ولا مفتاح تخزين ولا فحص إذن نطاق، لأن النطاق واحد ومعلن في
 * `host_permissions`.
 *
 * ⚠️ **الإضافة لا تنادي Supabase ولا Azure مباشرة.** مفتاح Supabase على
 * السيرفر، ورابط Azure يصل موقّعًا جاهزًا ولا يُعرض للمستخدم.
 */

import { BACKEND_URL, REQUEST_TIMEOUT_MS } from "../config.js";

/** رسالة موحّدة لتوقّف السيرفر أو انقطاع الشبكة. */
export const OFFLINE_MESSAGE =
  "تعذّر الاتصال بخدمة GovMind. تأكد من اتصالك بالإنترنت ثم أعد المحاولة.";

/**
 * خطأ يحمل رمز الحالة ومعرّف الخطأ النصّي من غلاف أخطاء الـBackend.
 *
 * `detail` نصّ السيرفر **كما ورد، أو `null` إن لم يرسل شيئًا**؛ و`message`
 * دائمًا نصّ صالح للعرض. الفصل بينهما مقصود: من يترجم الفشل يحتاج أن
 * يعرف هل تكلّم السيرفر أصلًا، فيختار عبارته حين يصمت بدل أن يرث عبارة
 * عامة كُتبت لغرض آخر.
 */
export class ApiError extends Error {
  constructor(message, status, code, detail = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
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
 * ينفّذ طلبًا ويعيد جسم الرد مُحلّلًا.
 *
 * كل فشل يخرج من هنا كـ`NetworkError` أو `ApiError` برسالة عربية جاهزة
 * للعرض — لا يصل المستخدم نصّ استثناء خام ولا رمز حالة عارٍ.
 */
export async function apiRequest(path, { method = "GET", body, token } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  // مهلة صريحة: `fetch` بلا مهلة قد يعلّق النافذة إلى الأبد على شبكة صامتة.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch {
    throw new NetworkError();
  } finally {
    clearTimeout(timer);
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
    const detail = (error.detail ?? "").trim() || null;
    throw new ApiError(
      detail || "حدث خطأ غير متوقع. حاول مرة أخرى.",
      response.status,
      error.code ?? "unknown_error",
      detail,
    );
  }

  return payload;
}

/* -------------------------------------------------------------------------
   الحساب
   ------------------------------------------------------------------------- */

/**
 * `POST /api/account/login` — يعيد الجلسة وملف العمل.
 *
 * **الحقلان المرسَلان هما البريد وكلمة المرور فقط.** لا رابط ولا مفتاح ولا
 * معرّف مساحة: كل ما يحتاجه العزل يُقرأ على السيرفر من ملف الحساب.
 */
export function login(email, password) {
  return apiRequest("/api/account/login", {
    method: "POST",
    body: { email, password },
  });
}

/**
 * `POST /api/account/register` — إنشاء حساب واشتراك تجريبي.
 *
 * **الحقول الأربعة المرسَلة بيانات المستخدم وحدها.** لا رابط ولا مفتاح
 * **ولا اسم جهة**: الاشتراك فردي، والمساحة التي يحتاجها عزل البيانات
 * يولّدها السيرفر ولا يراها العميل.
 *
 * يعيد جلسة جاهزة إن أمكن الدخول فورًا، أو `requires_email_confirmation`
 * إن كان المشروع يشترط تأكيد البريد.
 */
export function register({ fullName, email, password, confirmPassword }) {
  return apiRequest("/api/account/register", {
    method: "POST",
    body: {
      full_name: fullName,
      email,
      password,
      confirm_password: confirmPassword,
    },
  });
}

/** `GET /api/account/me` — ملف العمل. يعمل ولو كان الاشتراك منتهيًا. */
export function fetchAccount(token) {
  return apiRequest("/api/account/me", { token });
}

/* -------------------------------------------------------------------------
   الاشتراك والجهاز
   ------------------------------------------------------------------------- */

/** `GET /api/account/subscription` — الحالة والجهاز المفعّل. */
export function fetchSubscription(token) {
  return apiRequest("/api/account/subscription", { token });
}

/*
 * ⚠️ **لا `activateDevice` هنا، ولا يجوز أن يعود.**
 *
 * كانت الإضافة تنادي `POST /api/account/devices/activate` ببصمة عشوائية
 * تولّدها هي، فتشغل خانةَ الجهاز الوحيدة بهوية **لا يملكها الـRuntime**.
 * فإذا ثُبّت البرنامج وحاول تفعيل نفسه برمز التركيب رُدّ بـ23505، فيبقى
 * الحساب عالقًا: لا برنامج يعمل ولا خانة تُفرَّغ.
 *
 * التفعيل من الـRuntime وحده: هو من يولّد هوية الجهاز على الحاسب (DPAPI)
 * ويستهلك بها رمز التركيب بعد التثبيت.
 */

/**
 * `POST /api/account/devices/verify` — يتأكد أن هذا الجهاز هو المفعّل.
 *
 * **يُستدعى بدل `fetchSubscription` كلما وُجد جهاز مفعّل**: مسار القراءة
 * لا يعرف بصمة الطالب — إرسالها في رابط `GET` يضعها في سجلات السيرفر —
 * فلا يستطيع أن يقول إن كان المفعّل هو هذا الجهاز أم غيره.
 */
export function verifyDevice(token, deviceId) {
  return apiRequest("/api/account/devices/verify", {
    method: "POST",
    token,
    body: { device_id: deviceId },
  });
}

/**
 * `POST /api/account/devices/replace` — ينقل الاشتراك إلى هذا الجهاز.
 *
 * ⚠️ **كلمة المرور تُرسل من جديد.** رمز الدخول وحده لا يكفي لعملية توقف
 * GovMind على حاسب آخر؛ والتحقق يقع على السيرفر لا هنا.
 *
 * الإبطال والتفعيل عملية واحدة في القاعدة، فلا يبقى جهازان فعّالان ولا
 * يبقى الحساب بلا جهاز.
 */
export function replaceDevice(token, deviceId, deviceName, password) {
  return apiRequest("/api/account/devices/replace", {
    method: "POST",
    token,
    body: { device_id: deviceId, device_name: deviceName, password },
  });
}

/* -------------------------------------------------------------------------
   المثبّت
   ------------------------------------------------------------------------- */

/**
 * `POST /api/account/installation-session` — رمز تركيب لمرة واحدة.
 *
 * تطلبه الإضافة **قبل** التنزيل وتسلّمه إلى الـRuntime بعد التثبيت. هو
 * ما ينقل الثقة من المتصفح إلى البرنامج المثبَّت: الـRuntime يولّد هوية
 * الجهاز بنفسه، والإضافة لا تعرفها ولا تحتاجها.
 *
 * ⚠️ **يظهر مرة واحدة** ولا يمكن استرجاعه — يُخزَّن مجزّأً على السيرفر.
 */
export function requestInstallationSession(token) {
  return apiRequest("/api/account/installation-session", {
    method: "POST",
    token,
  });
}

/**
 * `POST /api/account/installer/download-url` — رابط SAS قصير العمر.
 *
 * ⚠️ **الرابط لا يُعرض للمستخدم ولا يُنسخ إلى الحافظة**: يُمرَّر مباشرة إلى
 * `chrome.downloads.download`. هو صالح للتحميل بلا هوية حتى ينتهي، فعرضه
 * دعوةٌ إلى مشاركته.
 */
export function requestInstallerUrl(token, deviceId) {
  return apiRequest("/api/account/installer/download-url", {
    method: "POST",
    token,
    body: { device_id: deviceId },
  });
}
