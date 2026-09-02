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
  /** إنشاء حساب جديد. */
  REGISTER: "register",
  /** سُجّل الحساب والمشروع يشترط تأكيد البريد قبل الدخول. */
  CONFIRM_EMAIL: "confirm-email",
  /** فحص أوّلي قصير عند الإقلاع — محايد، لا يَعِد بشيء. */
  CHECKING: "checking",

  /** اختيار طريقة البدء — نسخة عرض أكاديمية بلا رسوم. */
  CHOOSE_PLAN: "choose-plan",

  /** نُزّل المثبّت وينتظر أن يضغط المستخدم «فتح ملف التثبيت». */
  INSTALLER_READY: "installer-ready",

  /**
   * تعذّر على المتصفح فتح الملف — **حالة قائمة بذاتها لا خطأ عابر**.
   *
   * صلاحية `downloads.open` غير ممنوحة، أو نسخة متصفح لا تدعمها. الملف
   * يُظهَر في مجلده وتُطلب من المستخدم خطوة واحدة، **ولا يبدأ استطلاع
   * الـRuntime**: لم يُفتح شيء ليُنتظر.
   */
  OPEN_FAILED: "open-failed",

  /** لم يظهر الـRuntime بعد المهلة — شاشة تشخيص لا انتظار بلا نهاية. */
  INSTALL_HELP: "install-help",

  /**
   * تعذّر تسليم جلسة التركيب إلى الـRuntime.
   *
   * ⚠️ **غير «تعذّر تفعيل الجهاز»**: هنا لم يصل الرمز أصلًا — الـRuntime
   * لا يستجيب، أو تعذّر إصدار جلسة تركيب. خلطُ الاثنين يعطي المستخدم
   * إجراءً خاطئًا.
   */
  HANDOVER_FAILED: "handover-failed",

  /** وصل الرمز ورفض الخادم التفعيل — رسالة السبب من الخادم. */
  ACTIVATION_FAILED: "activation-failed",

  /** الدخول صحيح لكن تجهيز الحساب لم يكتمل. */
  NOT_PROVISIONED: "not-provisioned",
  /** اشتراك منتهٍ أو موقوف أو ملغى — رسالة السبب من السيرفر. */
  SUBSCRIPTION_BLOCKED: "subscription-blocked",
  /** الحساب مفعّل على جهاز آخر. */
  DEVICE_TAKEN: "device-taken",
  /**
   * ⚠️ **لم تعد شاشةً في المسار.** بقيت التسمية لأن `STEP_TITLES` عامّة،
   * لكن `resolveStep` لا يعيدها أبدًا: **الإضافة لا تفعّل جهازًا**، فهوية
   * الجهاز يولّدها الـRuntime بعد التثبيت ويستهلك بها رمز التركيب.
   */
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
 * @property {object|null} account ملف العمل، أو `null` إن لم يكتمل التجهيز.
 * @property {object|null} subscription رد `/api/account/subscription`.
 * @property {"idle"|"running"|"done"} download حالة تنزيل المثبّت.
 * @property {boolean} wantsRegister هل طلب المستخدم شاشة إنشاء الحساب؟
 * @property {boolean} awaitingEmailConfirmation هل سُجّل حساب ينتظر تأكيد بريده؟
 * @property {object|null} runtime آخر حالة قرأتها الإضافة من `/health`.
 * @property {boolean} handingOver هل يجري تسليم رمز التركيب الآن؟
 * @property {boolean} installStarted هل **قَبِل المتصفح فتح ملف المثبّت**؟
 * @property {boolean} openFailed هل رفض المتصفح فتح الملف؟
 * @property {string|null} handoverFailure سبب تعذّر تسليم رمز التركيب.
 * @property {string|null} activationFailure سبب رفض الخادم للتفعيل.
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
    wantsRegister = false,
    awaitingEmailConfirmation = false,
    planAcknowledged = false,
    installStarted = false,
    openFailed = false,
    handoverFailure = null,
    activationFailure = null,
    runtimeTimedOut = false,
    booting = false,
  } = state;

  // ٠) فحص الإقلاع القصير: شاشة محايدة تقول ما يحدث فعلًا ولا تَعِد بغيره.
  //    سقفها ثانية واحدة (`RUNTIME_DISCOVERY_TIMEOUT_MS`)، فلا تدوم.
  if (booting) return STEPS.CHECKING;

  // ١) بلا جلسة: ترحيب، ثم دخول أو إنشاء حساب.
  //
  //    **رسالة تأكيد البريد تسبق كل شيء** حين تكون قائمة: الحساب أُنشئ
  //    فعلًا، وإعادة المستخدم إلى نموذج الدخول تجعله يظنّ أن التسجيل فشل.
  if (!hasSession) {
    if (awaitingEmailConfirmation) return STEPS.CONFIRM_EMAIL;
    if (wantsRegister) return STEPS.REGISTER;
    // الترحيب مرة واحدة — من رآه وسجّل خروجه يعود إلى الدخول مباشرة.
    return welcomeSeen ? STEPS.SIGNIN : STEPS.WELCOME;
  }

  // ٢) دخول موثوق لكن تجهيز الحساب ناقص: لا شيء يستطيع فعله بنفسه.
  if (!account) return STEPS.NOT_PROVISIONED;

  // ٣) لم تصل حالة الاشتراك بعد (أو فشل جلبها): لا يُفترض شيء.
  if (!subscription) return STEPS.INSTALL;

  // ٤) اشتراك لا يسمح بالخدمة — قبل أي شاشة تثبيت أو تنزيل.
  if (!subscription.is_usable) return STEPS.SUBSCRIPTION_BLOCKED;

  // ٥) مفعّل على جهاز آخر: لا تثبيت هنا حتى يستبدله صاحب الحساب.
  //
  // ⚠️ **إلا أن يكون الجهاز المفعَّل هو هذا الحاسب.** بصمة المتصفح التي
  // تقارن بها `verify` ليست هوية الجهاز التي سجّلها الـRuntime، فالمقارنة
  // تعطي «جهاز آخر» على الحاسب نفسه بعد تثبيت ناجح. وجودُ Runtime **مربوط**
  // على الاسترجاع المحلي إثباتٌ أقوى من أي بصمة متصفح: لا يعمل إلا على
  // هذا الحاسب، ولا يُعدّ مربوطًا إلا ببيان اعتماد أصدره الخادم.
  if (isDeviceTaken(subscription) && !isThisDeviceLinked(runtime)) {
    return STEPS.DEVICE_TAKEN;
  }

  // ٦) **فشلٌ وقع فعلًا يسبق كل شاشة تقدّم.**
  //
  // ⚠️ بلا شرط `installStarted`: تسليم الرمز قد يقع عند الدخول نفسه —
  // Runtime مثبَّت من قبل ينتظر ربطًا — فلا تنزيل ولا فتحَ ملف في هذه
  // الجلسة. اشتراطُ `installStarted` هنا كان يترك المستخدم أمام شاشة
  // تقدّم فوق فشلٍ نهائي، وهو «الانتظار بلا نهاية» بعينه.
  //
  // والحالتان منفصلتان لأن إجراء المستخدم يختلف: تعذّرُ التسليم يُحلّ
  // بإكمال التثبيت أو إعادته، ورفضُ التفعيل يُحلّ باستبدال الجهاز أو
  // بتجديد الاشتراك.
  if (handoverFailure) return STEPS.HANDOVER_FAILED;
  if (activationFailure) return STEPS.ACTIVATION_FAILED;

  // ٧) الـRuntime موجود على الجهاز: حالته تسبق كل ما يخصّ المثبّت.
  //    من ثبّت البرنامج فعلًا لا يُعرض له «نزّل المثبّت» ولا شاشة خطة.
  if (runtime) {
    // جاهز = مثبَّت ومفعَّل. لا شرط عليه: هذه أفضل حالة ممكنة.
    if (runtime.is_ready) return STEPS.INSTALLED;

    // ⚠️ **شاشات التقدّم مشروطة بأن يكون المستخدم قد بدأ التثبيت.**
    //
    // كان يكفي أن يجد الإقلاعُ Runtime عالقًا في `phase: "activating"` —
    // بقيّةَ تثبيتٍ سابق متعثّر — ليرى المستخدم «جارٍ تفعيل هذا الجهاز»
    // فور فتح النافذة، بلا جلسة تركيب ولا تنزيل ولا فعلٍ منه. شاشةُ تقدّمٍ
    // عن عملية لم يبدأها أحد.
    //
    // `installStarted` لا يصير صحيحًا إلا بعد اكتمال التنزيل **وقبولِ
    // المتصفح فتحَ الملف** — انظر `doOpenInstaller`.
    if (installStarted) {
      if (handingOver || runtime.phase === "activating") {
        return STEPS.ACTIVATING_DEVICE;
      }
      // الـRuntime يعمل ولم يُربط بعد: ما زلنا في مرحلة إكمال التثبيت،
      // **لا في مرحلة تفعيل الجهاز**.
      if (runtime.needs_activation) return STEPS.AWAITING_RUNTIME;
      // ينزّل المودل أو يتحقق منه أو يجهّزه — كلها «جارٍ التجهيز».
      return STEPS.PREPARING_MODEL;
    }

    // Runtime موجود لكن غير جاهز ولم يبدأ المستخدم تثبيتًا في هذه الجلسة:
    // يُكمل المسار الطبيعي أدناه بدل أن يُحبس أمام تقدّمٍ ليس تقدّمه.
  }

  // ٨) اختيار طريقة البدء، **مرة واحدة لكل حساب** قبل التثبيت.
  if (!planAcknowledged) return STEPS.CHOOSE_PLAN;

  // ٩) التنزيل جارٍ.
  if (download === "running") return STEPS.DOWNLOADING;

  // ١٠) اكتمل التنزيل.
  //
  // ⚠️ **الاستطلاع لا يبدأ إلا بعد أن يقبل المتصفح فتح الملف فعلًا.**
  // كان يكفي أن يضغط المستخدم زرَّ إقرارٍ بأنه فتح المثبّت — إقرارٌ منه لا
  // حدثٌ وقع — فتنتظر الإضافة برنامجًا لم يُفتح ملفُه أصلًا. الآن
  // `installStarted` لا تصير صحيحة إلا حين تعود `chrome.downloads.open`
  // بالقبول؛ انظر `doOpenInstaller`.
  if (download === "done") {
    if (!installStarted) {
      // رفض المتصفح الفتح: شاشة تقول الخطوة الواحدة الباقية، **بلا
      // استطلاع** — لا شيء فُتح لينتظره أحد.
      return openFailed ? STEPS.OPEN_FAILED : STEPS.INSTALLER_READY;
    }
    // قَبِل المتصفح الفتح: ننتظر ظهور الـRuntime — بمهلة منتهية.
    return runtimeTimedOut ? STEPS.INSTALL_HELP : STEPS.AWAITING_RUNTIME;
  }

  // ١١) لا شيء بعد: ابدأ بتثبيت GovMind.
  //
  // ⚠️ **هنا كان العطل.** كان الشرط `subscription.requires_activation`
  // يعيد `STEPS.ACTIVATE`، فيرى صاحبُ أول جهاز شاشةَ «تفعيل هذا الجهاز»
  // بدل «تثبيت GovMind»، وزرُّها يفعّل **بصمة المتصفح** العشوائية فيشغل
  // خانةَ الجهاز الوحيدة بهوية لا يملكها الـRuntime. فإذا ثُبّت البرنامج
  // ورام تفعيل نفسه رُدّ بـ23505 وبقي الحساب عالقًا بلا برنامج يعمل.
  //
  // **الإضافة لا تفعّل جهازًا إطلاقًا.** الهوية يولّدها الـRuntime على
  // الحاسب (DPAPI)، ويستهلك بها رمز التركيب بعد التثبيت.
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

/**
 * هل يوجد على هذا الحاسب Runtime **مربوط بالحساب**؟
 *
 * `needs_activation === false` تعني أن الـRuntime يحمل بيان اعتماد أصدره
 * الخادم بعد استبدال جلسة تركيب صالحة. لا يمكن أن يوجد ذلك على حاسب لم
 * يُربط، ولا يمكن أن يبقى بعد استبدال الجهاز — الخادم يبطله.
 */
export function isThisDeviceLinked(runtime) {
  return Boolean(runtime) && runtime.needs_activation === false;
}

/** نصّ العنوان الظاهر لكل شاشة — يستعمله العنوان الرئيسي وقارئ الشاشة. */
export const STEP_TITLES = Object.freeze({
  [STEPS.WELCOME]: "مرحبًا بك في GovMind",
  [STEPS.SIGNIN]: "تسجيل الدخول",
  [STEPS.REGISTER]: "إنشاء حساب جديد",
  [STEPS.CONFIRM_EMAIL]: "أكّد بريدك الإلكتروني",
  [STEPS.NOT_PROVISIONED]: "الحساب غير مكتمل التجهيز",
  [STEPS.SUBSCRIPTION_BLOCKED]: "الاشتراك لا يسمح بالاستخدام",
  [STEPS.DEVICE_TAKEN]: "الحساب مفعّل على جهاز آخر",
  [STEPS.CHECKING]: "جاري التحقق...",
  [STEPS.CHOOSE_PLAN]: "اختر طريقة البدء",
  [STEPS.ACTIVATE]: "تفعيل هذا الجهاز",
  [STEPS.INSTALL]: "تثبيت GovMind",
  [STEPS.DOWNLOADING]: "جارٍ التنزيل",
  [STEPS.INSTALLER_READY]: "تم تنزيل GovMind",
  [STEPS.OPEN_FAILED]: "افتح ملف التثبيت من المجلد",
  [STEPS.INSTALL_HELP]: "لم يبدأ GovMind بعد",
  // ⚠️ **ليست «جارٍ تفعيل هذا الجهاز».** لا تفعيل يجري بعد: المثبّت
  // يعمل، والـRuntime لم يظهر. تسميةُ ما لا يحدث هي ما أربك العميل.
  [STEPS.AWAITING_RUNTIME]: "بانتظار اكتمال تثبيت GovMind",
  [STEPS.ACTIVATING_DEVICE]: "جارٍ تفعيل الجهاز",
  [STEPS.HANDOVER_FAILED]: "تعذّر إكمال ربط الجهاز",
  [STEPS.ACTIVATION_FAILED]: "تعذّر تفعيل هذا الجهاز",
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
  [STEPS.REGISTER]: 2,
  [STEPS.CHOOSE_PLAN]: 3,
  [STEPS.INSTALL]: 4,
  [STEPS.DOWNLOADING]: 4,
  [STEPS.INSTALLER_READY]: 5,
  [STEPS.OPEN_FAILED]: 5,
  [STEPS.AWAITING_RUNTIME]: 5,
  [STEPS.ACTIVATING_DEVICE]: 6,
  [STEPS.PREPARING_MODEL]: 6,
  [STEPS.INSTALLED]: 7,
});

/** إجمالي خطوات المسار الناجح. */
export const TOTAL_STEPS = 7;
