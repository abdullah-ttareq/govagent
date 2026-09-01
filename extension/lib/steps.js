/**
 * منطق التدفّق الإرشادي — **دالة نقية واحدة تقرّر أي شاشة تُعرض.**
 *
 * لماذا مفصولة عن `popup.js`؟ لأن التدفّق تسع حالات متشابكة (جلسة، حساب،
 * اشتراك، جهاز، تنزيل)، وتشابكها في معالِجات أحداث DOM يجعل نصفها غير
 * قابل للاختبار عمليًا. هنا هي **حالة داخلة ← معرّف شاشة خارج**، بلا DOM
 * ولا شبكة ولا `chrome.*`، فتُختبر الحالات التسع كلها في ملّي ثانية.
 *
 * `popup.js` لا يقرّر شيئًا: يجمع الحالة، ينادي {@link resolveStep}، ثم
 * يُظهر الشاشة التي عادت. قاعدة واحدة في مكان واحد.
 */

/**
 * معرّفات الشاشات، بالترتيب الذي يمرّ بها المستخدم.
 *
 * @typedef {(
 *   "welcome" | "signin" | "not-provisioned" | "subscription-blocked" |
 *   "device-taken" | "activate" | "install" | "downloading" |
 *   "awaiting-runtime" | "activating-device" | "preparing-model" | "installed"
 * )} StepId
 */
export const STEPS = Object.freeze({
  /** ترحيب وشرح للخطوات — أول ما يراه من لم يسجّل الدخول بعد. */
  WELCOME: "welcome",
  /** نموذج البريد وكلمة المرور. */
  SIGNIN: "signin",
  /** الحساب صحيح لكن لا جهة له — يحتاج مسؤول النظام. */
  NOT_PROVISIONED: "not-provisioned",
  /** اشتراك منتهٍ أو موقوف أو ملغى — رسالة السبب من السيرفر. */
  SUBSCRIPTION_BLOCKED: "subscription-blocked",
  /** الحساب مفعّل على جهاز آخر. */
  DEVICE_TAKEN: "device-taken",
  /** تفعيل هذا الجهاز. */
  ACTIVATE: "activate",
  /** زر «ثبّت GovMind». */
  INSTALL: "install",
  /** شريط التقدّم أثناء التنزيل. */
  DOWNLOADING: "downloading",
  /**
   * المثبّت نُزّل، وننتظر أن يفتحه المستخدم فيظهر الـRuntime.
   *
   * **حلّت محلّ شاشة «اكتمل التنزيل» المنفصلة.** الشاشتان كانتا تقولان
   * الشيء نفسه — «افتح الملف ووافق على نافذة ويندوز» — والفرق أن هذه
   * تنتظر النتيجة كذلك. شاشتان بالنصّ نفسه تربكان ولا تفيدان.
   */
  AWAITING_RUNTIME: "awaiting-runtime",
  /** عُثر على الـRuntime، وجارٍ تسليمه رمز التركيب. */
  ACTIVATING_DEVICE: "activating-device",
  /** الـRuntime ينزّل المودل ويتحقق منه. */
  PREPARING_MODEL: "preparing-model",
  /** كل شيء جاهز — يمكن فتح GovMind. */
  INSTALLED: "installed",
});

/**
 * مراحل الـRuntime التي تعني «ما زال يجهّز».
 *
 * مصدرها `runtime/govmind_runtime/state.py` — القائمتان يجب أن تبقيا
 * متطابقتين، ويحرس ذلك اختبار في `tests/steps.test.js`.
 */
export const RUNTIME_BUSY_PHASES = Object.freeze([
  "activating",
  "downloading_model",
  "verifying_model",
  "starting_model",
]);

/**
 * @typedef {object} FlowState
 * @property {boolean} hasSession هل يوجد رمز دخول محفوظ وصالح المدة؟
 * @property {boolean} welcomeSeen هل تجاوز المستخدم شاشة الترحيب من قبل؟
 * @property {object|null} account ملف العمل، أو `null` إن لم يُربط الحساب بجهة.
 * @property {object|null} subscription رد `/api/account/subscription`.
 * @property {"idle"|"running"|"done"} download حالة تنزيل المثبّت.
 * @property {object|null} runtime آخر حالة قرأتها الإضافة من `/health`.
 * @property {boolean} handingOver هل يجري تسليم رمز التركيب الآن؟
 */

/**
 * يعيد معرّف الشاشة التي يجب عرضها للحالة المعطاة.
 *
 * الترتيب مقصود: **الأشدّ حجبًا أولًا.** لا معنى لعرض «ثبّت GovMind» لمن
 * انتهى اشتراكه لأن حالة التنزيل عنده `done` من جلسة سابقة.
 *
 * @param {Partial<FlowState>} state
 * @returns {StepId}
 */
export function resolveStep(state = {}) {
  const {
    hasSession = false,
    welcomeSeen = false,
    account = null,
    subscription = null,
    download = "idle",
    runtime = null,
    handingOver = false,
  } = state;

  // ١) بلا جلسة: ترحيب ثم دخول. الترحيب مرة واحدة — من رآه وسجّل خروجه
  //    يعود إلى الدخول مباشرة، فتكراره عليه في كل مرة إبطاء بلا فائدة.
  if (!hasSession) return welcomeSeen ? STEPS.SIGNIN : STEPS.WELCOME;

  // ٢) حساب موثوق بلا جهة: لا شيء يستطيع فعله بنفسه.
  if (!account) return STEPS.NOT_PROVISIONED;

  // ٣) لم تصل حالة الاشتراك بعد (أو فشل جلبها): لا يُفترض شيء.
  if (!subscription) return STEPS.ACTIVATE;

  // ٤) اشتراك لا يسمح بالخدمة — قبل أي شاشة تفعيل أو تنزيل.
  if (!subscription.is_usable) return STEPS.SUBSCRIPTION_BLOCKED;

  // ٥) مفعّل على جهاز آخر: التفعيل هنا مستحيل حتى يبطله المسؤول.
  if (isDeviceTaken(subscription)) return STEPS.DEVICE_TAKEN;

  // ٦) لا جهاز مفعّلًا بعد، أو المفعّل ليس هذا الجهاز.
  if (subscription.requires_activation) return STEPS.ACTIVATE;

  // ٧) الـRuntime موجود على الجهاز: حالته تسبق كل ما يخصّ المثبّت.
  //    من ثبّت البرنامج فعلًا لا يُعرض له «نزّل المثبّت» من جديد.
  if (runtime) {
    if (runtime.is_ready) return STEPS.INSTALLED;
    if (handingOver || runtime.phase === "activating") {
      return STEPS.ACTIVATING_DEVICE;
    }
    if (runtime.needs_activation) return STEPS.AWAITING_RUNTIME;
    // ينزّل المودل أو يتحقق منه أو يجهّزه — كلها «جارٍ التجهيز».
    return STEPS.PREPARING_MODEL;
  }

  // ٨) نُزّل المثبّت وننتظر أن يفتحه المستخدم فيظهر الـRuntime.
  if (download === "done") return STEPS.AWAITING_RUNTIME;

  // ٩) لا Runtime ولا تنزيل مكتمل: التنزيل وحالاته.
  if (download === "running") return STEPS.DOWNLOADING;
  return STEPS.INSTALL;
}

/**
 * هل الاشتراك مفعّل على **جهاز آخر**؟
 *
 * الشرط مركّب: يوجد جهاز مفعّل **و** ليس هذا الجهاز. غياب `device` يعني
 * أنه لم يُفعَّل شيء بعد، لا أن جهازًا آخر أخذه.
 */
export function isDeviceTaken(subscription) {
  const device = subscription?.device;
  return Boolean(device) && device.is_current_device === false;
}

/** نصّ العنوان الظاهر لكل شاشة — يستعمله العنوان الرئيسي وقارئ الشاشة. */
export const STEP_TITLES = Object.freeze({
  [STEPS.WELCOME]: "مرحبًا بك في GovMind",
  [STEPS.SIGNIN]: "تسجيل الدخول",
  [STEPS.NOT_PROVISIONED]: "الحساب غير مرتبط بجهة",
  [STEPS.SUBSCRIPTION_BLOCKED]: "الاشتراك لا يسمح بالاستخدام",
  [STEPS.DEVICE_TAKEN]: "الحساب مفعّل على جهاز آخر",
  [STEPS.ACTIVATE]: "تفعيل هذا الجهاز",
  [STEPS.INSTALL]: "تثبيت GovMind",
  [STEPS.DOWNLOADING]: "جارٍ التنزيل",
  [STEPS.AWAITING_RUNTIME]: "بانتظار فتح المثبّت",
  [STEPS.ACTIVATING_DEVICE]: "جارٍ تفعيل الجهاز",
  [STEPS.PREPARING_MODEL]: "جارٍ تجهيز GovMind",
  [STEPS.INSTALLED]: "GovMind جاهز",
});

/**
 * رقم الخطوة في المؤشّر العلوي، أو `0` لشاشة خارج المسار.
 *
 * الشاشات المانعة (اشتراك منتهٍ، جهاز آخر) لا رقم لها: ليست خطوة يمرّ بها
 * الناجح، وإعطاؤها رقمًا يوهم بأن بعدها خطوة يبلغها المستخدم بنفسه.
 */
export const STEP_NUMBERS = Object.freeze({
  [STEPS.WELCOME]: 1,
  [STEPS.SIGNIN]: 2,
  [STEPS.ACTIVATE]: 3,
  [STEPS.INSTALL]: 4,
  [STEPS.DOWNLOADING]: 4,
  [STEPS.AWAITING_RUNTIME]: 5,
  [STEPS.ACTIVATING_DEVICE]: 6,
  [STEPS.PREPARING_MODEL]: 6,
  [STEPS.INSTALLED]: 7,
});

/** إجمالي خطوات المسار الناجح. */
export const TOTAL_STEPS = 7;
