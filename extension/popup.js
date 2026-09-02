/**
 * نافذة GovMind — تدفّق إرشادي من تسع شاشات، بلا محادثة وبلا قراءة صفحات.
 *
 * **ما تفعله هذه الإضافة:** دخول، فحص اشتراك، تفعيل جهاز واحد، تنزيل
 * المثبّت بتقدّم، ثم إرشاد المستخدم إلى فتحه.
 *
 * **ما لا تفعله ولن تفعله:**
 * - لا محادثة ولا إرسال نصّ إلى أي مودل.
 * - لا `content_scripts` ولا قراءة أي صفحة — لا صلاحية لذلك في
 *   `manifest.json` أصلًا، فليست مسألة انضباط.
 * - لا تعرض رابط Azure ولا تسمح بنسخه.
 * - **لا تفتح ملفًا تنفيذيًا إلا من نقرة المستخدم على «فتح ملف التثبيت»**،
 *   ولا تتخطّى ولا تُخفي أي حماية في ويندوز: UAC وSmartScreen وSmart App
 *   Control تعمل كلها بعد الفتح كما تعمل مع أي ملف نزّله المستخدم بنفسه.
 * - لا تطلب من المستخدم رابطًا ولا مفتاحًا.
 *
 * **القرار في مكان واحد:** `lib/steps.js` دالة نقية تقول أي شاشة تُعرض،
 * وهذا الملف يجمع الحالة ويعرض ما تقوله. لا شرط تدفّق مكرَّر هنا.
 */

import { RUNTIME_WAIT_MS } from "./config.js";
import {
  fetchSubscription,
  login,
  register,
  replaceDevice,
  requestInstallationSession,
  requestInstallerUrl,
  verifyDevice,
} from "./lib/api.js";
import { ensureDeviceId, ensureDeviceName } from "./lib/device.js";
import {
  cancelDownload,
  formatBytes,
  openDownload,
  queryDownload,
  percentOf,
  showInFolder,
  startDownload,
  watchDownload,
} from "./lib/download.js";
import { actionLabel, describeFailure } from "./lib/errors.js";
import {
  ActivationFailedError,
  HandoverFailedError,
  findRuntime,
  handOverToken,
  openGovMind,
  waitForRuntime,
} from "./lib/runtime.js";
import {
  acknowledgePlan,
  clearInstallProgress,
  clearInstallToken,
  clearSession,
  getInstallProgress,
  getInstallToken,
  getRuntimePort,
  getSession,
  getWelcomeSeen,
  hasAcknowledgedPlan,
  isSessionUsable,
  pruneLegacyKeys,
  reconcileInstallState,
  setInstallProgress,
  setInstallToken,
  setRuntimePort,
  setSession,
  setWelcomeSeen,
  updateAccount,
} from "./lib/storage.js";
import { STEPS, STEP_NUMBERS, TOTAL_STEPS, resolveStep } from "./lib/steps.js";

/* =========================================================================
   عناصر الصفحة
   ========================================================================= */
const el = {
  steps: document.getElementById("steps"),
  alert: document.getElementById("alert"),
  alertMessage: document.getElementById("alert-message"),
  alertAction: document.getElementById("alert-action"),
  footer: document.getElementById("footer"),
  footerAccount: document.getElementById("footer-account"),

  welcomeNext: document.getElementById("welcome-next"),

  signinForm: document.getElementById("signin-form"),
  signinEmail: document.getElementById("signin-email"),
  signinPassword: document.getElementById("signin-password"),
  signinSubmit: document.getElementById("signin-submit"),

  goRegister: document.getElementById("go-register"),
  goLogin: document.getElementById("go-login"),

  registerForm: document.getElementById("register-form"),
  registerName: document.getElementById("register-name"),
  registerEmail: document.getElementById("register-email"),
  registerPassword: document.getElementById("register-password"),
  registerConfirm: document.getElementById("register-confirm"),
  registerSubmit: document.getElementById("register-submit"),

  confirmEmailMessage: document.getElementById("confirm-email-message"),
  confirmEmailLogin: document.getElementById("confirm-email-login"),

  blockedTitle: document.getElementById("blocked-title"),
  blockedMessage: document.getElementById("blocked-message"),
  blockedFacts: document.getElementById("blocked-facts"),

  deviceTakenMessage: document.getElementById("device-taken-message"),
  deviceTakenFacts: document.getElementById("device-taken-facts"),
  replaceForm: document.getElementById("replace-form"),
  replacePassword: document.getElementById("replace-password"),
  replaceSubmit: document.getElementById("replace-submit"),

  demoBadge: document.getElementById("demo-badge"),
  planTrialStart: document.getElementById("plan-trial-start"),
  planPaidStart: document.getElementById("plan-paid-start"),

  readyFileName: document.getElementById("ready-file-name"),
  readyShow: document.getElementById("ready-show"),
  readyOpen: document.getElementById("ready-open"),

  openFailedMessage: document.getElementById("open-failed-message"),
  openFailedCheck: document.getElementById("open-failed-check"),
  openFailedShow: document.getElementById("open-failed-show"),

  installHelpMessage: document.getElementById("install-help-message"),
  helpRetry: document.getElementById("help-retry"),
  helpShow: document.getElementById("help-show"),
  helpRestart: document.getElementById("help-restart"),

  handoverFailedMessage: document.getElementById("handover-failed-message"),
  handoverRetry: document.getElementById("handover-retry"),
  handoverRestart: document.getElementById("handover-restart"),

  activationFailedMessage: document.getElementById("activation-failed-message"),
  activationRetry: document.getElementById("activation-retry"),

  installFacts: document.getElementById("install-facts"),
  installStart: document.getElementById("install-start"),

  progress: document.getElementById("progress"),
  progressBar: document.getElementById("progress-bar"),
  progressLabel: document.getElementById("progress-label"),
  downloadCancel: document.getElementById("download-cancel"),

  awaitingHelp: document.getElementById("awaiting-help"),
  awaitingLabel: document.getElementById("awaiting-label"),
  awaitingShow: document.getElementById("awaiting-show"),

  preparingMessage: document.getElementById("preparing-message"),
  preparingProgress: document.getElementById("preparing-progress"),
  preparingBar: document.getElementById("preparing-bar"),
  preparingLabel: document.getElementById("preparing-label"),

  installedFacts: document.getElementById("installed-facts"),
  installedOpen: document.getElementById("installed-open"),

  themeRoot: document.getElementById("theme-root"),
  themeTrigger: document.getElementById("theme-trigger"),
  themeMenu: document.getElementById("theme-menu"),
  themeIcon: document.getElementById("theme-icon"),
};

/* =========================================================================
   الحالة

   كائن واحد يصف كل ما يعرفه التطبيق. أي تغيّر يمرّ بـ`render()`، فلا تُحدَّث
   عقدة DOM من مكانين.
   ========================================================================= */
const state = {
  session: null,
  account: null,
  subscription: null,
  welcomeSeen: false,
  download: "idle", // idle | running | done
  downloadId: null,
  downloadFileName: "",
  stopWatching: null,
  busy: false,
  /** آخر حالة قرأتها الإضافة من `/health` الخاص بالـRuntime. */
  runtime: null,
  runtimePort: null,
  /** هل يجري تسليم رمز التركيب الآن؟ */
  handingOver: false,
  //: هل أقرّ صاحب الحساب طريقة البدء؟ يُقرأ من التخزين عند الإقلاع.
  planAcknowledged: false,
  //: هل **قَبِل المتصفح فتح ملف المثبّت**؟ شرط بدء استطلاع الـRuntime.
  //
  //: ⚠️ ليست «هل أقرّ المستخدم أنه فتحه». الفرق هو العطل نفسه: الإقرار
  //: كان يبدأ انتظارًا لبرنامج ما زال ملفُّه مغلقًا في مجلد التنزيلات.
  installStarted: false,
  //: رفض المتصفح فتح الملف — حالة قائمة بذاتها، **بلا استطلاع**.
  openFailed: false,
  //: نقرةُ فتحٍ جارية. حارس متزامن يمنع فتح المثبّت مرتين بنقرتين سريعتين.
  openingInstaller: false,
  //: سبب تعذّر تسليم رمز التركيب، أو `null`.
  handoverFailure: null,
  //: سبب رفض الخادم للتفعيل، أو `null`.
  activationFailure: null,
  //: انتهت مهلة انتظار الـRuntime — شاشة تشخيص لا انتظار بلا نهاية.
  runtimeTimedOut: false,
  //: الفحص الأوّلي جارٍ. سقفه ثانية واحدة، وشاشته محايدة.
  booting: true,
  /** يوقف استطلاع الـRuntime عند إغلاق النافذة. */
  pollAbort: false,
  /** هل طلب المستخدم شاشة إنشاء الحساب؟ */
  wantsRegister: false,
  /** حساب أُنشئ وينتظر تأكيد بريده — لا جلسة له بعد. */
  awaitingEmailConfirmation: false,
  /** البريد الذي سُجّل، لعرضه في رسالة التأكيد. */
  registeredEmail: "",
};

/* =========================================================================
   العرض
   ========================================================================= */
function showAlert(message, action = "none") {
  el.alertMessage.textContent = message;
  const label = actionLabel(action);
  el.alertAction.hidden = label === null;
  el.alertAction.textContent = label ?? "";
  el.alertAction.dataset.action = action;
  el.alert.hidden = false;
}

function clearAlert() {
  el.alert.hidden = true;
  el.alertAction.hidden = true;
}

/** يبني قائمة تعريف من أزواج، متجاهلًا ما لا قيمة له. */
function renderFacts(container, pairs) {
  container.replaceChildren();
  for (const [term, value] of pairs) {
    if (value === null || value === undefined || value === "") continue;
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = term;
    // `textContent` لا `innerHTML`: القيم تأتي من السيرفر، ولا شيء منها
    // يُفسَّر كـHTML في هذه النافذة.
    dd.textContent = value;
    row.append(dt, dd);
    container.append(row);
  }
}

/** يعرض تاريخًا بالميلادي المختصر، أو نصًّا فارغًا إن كان غير صالح. */
function formatDate(value) {
  if (!value) return "";
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return "";
  return moment.toLocaleDateString("ar-SA-u-ca-gregory", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

const STATUS_LABELS = {
  trial: "فترة تجريبية",
  active: "فعّال",
  expired: "منتهٍ",
  suspended: "موقوف",
  cancelled: "ملغى",
};

function updateSteps(step) {
  const current = STEP_NUMBERS[step] ?? 0;
  el.steps.setAttribute("aria-hidden", String(current === 0));
  for (const dot of el.steps.querySelectorAll(".steps__dot")) {
    const index = Number(dot.dataset.step);
    if (index < current) dot.dataset.state = "done";
    else if (index === current) dot.dataset.state = "current";
    else delete dot.dataset.state;
  }
  el.steps.setAttribute("aria-label", `الخطوة ${current} من ${TOTAL_STEPS}`);
}

/** يُظهر شاشة واحدة ويخفي البقية. مصدر العرض الوحيد. */
function render() {
  const step = resolveStep({
    hasSession: isSessionUsable(state.session),
    welcomeSeen: state.welcomeSeen,
    account: state.account,
    subscription: state.subscription,
    download: state.download,
    runtime: state.runtime,
    handingOver: state.handingOver,
    wantsRegister: state.wantsRegister,
    awaitingEmailConfirmation: state.awaitingEmailConfirmation,
    planAcknowledged: state.planAcknowledged,
    installStarted: state.installStarted,
    openFailed: state.openFailed,
    handoverFailure: state.handoverFailure,
    activationFailure: state.activationFailure,
    runtimeTimedOut: state.runtimeTimedOut,
    booting: state.booting,
  });

  for (const screen of document.querySelectorAll(".screen")) {
    screen.hidden = screen.id !== `screen-${step}`;
  }
  updateSteps(step);

  el.footer.hidden = !state.account;
  if (state.account) {
    el.footerAccount.textContent = state.account.email ?? "";
  }

  if (step === STEPS.SUBSCRIPTION_BLOCKED) renderBlocked();
  if (step === STEPS.DEVICE_TAKEN) renderDeviceTaken();
  if (step === STEPS.INSTALL) renderInstall();
  if (step === STEPS.INSTALLER_READY) {
    el.readyFileName.textContent = state.downloadFileName || "المثبّت";
  }
  if (step === STEPS.OPEN_FAILED && el.openFailedMessage) {
    // النصّ يسمّي الملف كما نُزّل، فيجده المستخدم في المجلد بلا بحث.
    el.openFailedMessage.textContent =
      `افتح ${state.downloadFileName || "GovMindSetup.exe"} من المجلد لإكمال التثبيت.`;
  }
  if (step === STEPS.HANDOVER_FAILED && el.handoverFailedMessage) {
    el.handoverFailedMessage.textContent = state.handoverFailure;
  }
  if (step === STEPS.ACTIVATION_FAILED && el.activationFailedMessage) {
    el.activationFailedMessage.textContent = state.activationFailure;
  }
  if (step === STEPS.CONFIRM_EMAIL) {
    el.confirmEmailMessage.textContent =
      `أرسلنا رسالة تأكيد إلى ${state.registeredEmail}. ` +
      "لن تتمكن من الدخول قبل تأكيد بريدك.";
  }
  if (step === STEPS.PREPARING_MODEL) renderPreparing();
  if (step === STEPS.INSTALLED) renderInstalled();
  return step;
}

function renderBlocked() {
  const subscription = state.subscription ?? {};
  el.blockedTitle.textContent =
    subscription.status === "suspended"
      ? "الاشتراك موقوف"
      : subscription.status === "cancelled"
        ? "الاشتراك ملغى"
        : "انتهى الاشتراك";
  // رسالة السيرفر تحمل التاريخ والسبب، فتُعرض كما وردت.
  el.blockedMessage.textContent =
    subscription.blocked_reason ??
    "اشتراكك لا يسمح باستخدام الخدمة حاليًا. تواصل مع الدعم.";
  renderFacts(el.blockedFacts, [
    ["الحالة", STATUS_LABELS[subscription.status] ?? subscription.status],
    ["تاريخ الانتهاء", formatDate(subscription.expires_at)],
  ]);
}

function renderDeviceTaken() {
  const device = state.subscription?.device ?? {};
  el.deviceTakenMessage.textContent =
    `اشتراكك مفعّل حاليًا على «${device.device_name ?? "جهاز آخر"}»، ` +
    "فلا يمكن تفعيله على هذا الجهاز في الوقت نفسه.";
  renderFacts(el.deviceTakenFacts, [
    ["الجهاز المفعّل", device.device_name],
    ["تاريخ التفعيل", formatDate(device.activated_at)],
    ["آخر استخدام", formatDate(device.last_seen_at)],
  ]);
  // الحقل لا يحمل كلمة مرور من زيارة سابقة للشاشة.
  if (el.replacePassword) el.replacePassword.value = "";
}

/** يعرض تقدّم الـRuntime وهو ينزّل المودل أو يتحقق منه. */
function renderPreparing() {
  const runtime = state.runtime ?? {};
  el.preparingMessage.textContent =
    runtime.message || "جارٍ تجهيز GovMind على هذا الجهاز…";

  const percent = runtime.progress;
  if (typeof percent === "number") {
    delete el.preparingBar.dataset.indeterminate;
    el.preparingBar.style.inlineSize = `${percent}%`;
    el.preparingProgress.setAttribute("aria-valuenow", String(percent));
    el.preparingLabel.textContent =
      runtime.total_bytes > 0
        ? `${percent}٪ — ${formatBytes(runtime.downloaded_bytes)} من ${formatBytes(runtime.total_bytes)}`
        : `${percent}٪`;
    return;
  }

  // مرحلة بلا نسبة (تحقّق أو تحميل في الذاكرة): حركة مستمرة لا رقم كاذب.
  el.preparingBar.dataset.indeterminate = "true";
  el.preparingBar.style.removeProperty("inline-size");
  el.preparingProgress.removeAttribute("aria-valuenow");
  el.preparingLabel.textContent = "";
}

function renderInstalled() {
  const runtime = state.runtime ?? {};
  renderFacts(el.installedFacts, [
    ["الجهاز", runtime.device_name],
    ["الحساب", state.account?.email],
    [
      "حالة الاشتراك",
      STATUS_LABELS[runtime.subscription_status ?? state.subscription?.status] ?? "",
    ],
  ]);
}

function renderInstall() {
  const subscription = state.subscription ?? {};
  renderFacts(el.installFacts, [
    ["الحساب", state.account?.email],
    ["حالة الاشتراك", STATUS_LABELS[subscription.status] ?? ""],
    ["ينتهي في", formatDate(subscription.expires_at)],
  ]);
}

/* =========================================================================
   معالجة الفشل
   ========================================================================= */
async function handleFailure(caught, fallback) {
  // أي فشل ينهي فحص الإقلاع: الشاشة المحايدة لا تصلح سياقًا لرسالة خطأ.
  state.booting = false;
  const failure = describeFailure(caught, fallback);
  if (failure.sessionLost) {
    await clearSession();
    state.session = null;
    state.account = null;
    state.subscription = null;
  }
  showAlert(failure.message, failure.action);
  render();
}

/** يعطّل زرًّا أثناء عملية شبكية ويعيده بعدها. */
async function withBusy(button, work) {
  if (state.busy) return;
  state.busy = true;
  if (button) button.disabled = true;
  try {
    await work();
  } finally {
    state.busy = false;
    if (button) button.disabled = false;
  }
}

/* =========================================================================
   جلب الحالة
   ========================================================================= */
/**
 * يقرأ حالة الاشتراك.
 *
 * **يمرّ بـ`verify` لا بـ`subscription` وحده:** مسار القراءة لا يعرف بصمة
 * الطالب فلا يستطيع أن يقول إن كان الجهاز المفعّل هو هذا الجهاز. المسار
 * الأول يعطي الصورة، والثاني يحسم «أهو أنا؟».
 */
async function refreshSubscription() {
  const token = state.session?.token;
  if (!token) return;

  const summary = await fetchSubscription(token);

  if (!summary.device) {
    state.subscription = summary;
    return;
  }

  const deviceId = await ensureDeviceId();
  try {
    state.subscription = await verifyDevice(token, deviceId);
  } catch (caught) {
    // ٤٠٩ هنا **ليست خطأً بل جواب**: هذا ليس الجهاز المفعّل. الصورة
    // العامة تكفي لعرض شاشة «مفعّل على جهاز آخر».
    if (caught?.status === 409) {
      state.subscription = {
        ...summary,
        requires_activation: true,
        device: { ...summary.device, is_current_device: false },
      };
      return;
    }
    throw caught;
  }
}

/* =========================================================================
   الأفعال
   ========================================================================= */
async function doSignIn(event) {
  event.preventDefault();
  clearAlert();

  const email = el.signinEmail.value.trim();
  const password = el.signinPassword.value;
  if (!email || !password) {
    showAlert("أدخل البريد الإلكتروني وكلمة المرور.", "none");
    return;
  }

  await withBusy(el.signinSubmit, async () => {
    try {
      const session = await login(email, password);
      // كلمة المرور تُمحى من الحقل فور نجاح الدخول: النافذة قد تبقى مفتوحة.
      el.signinPassword.value = "";

      await adoptSession({
        accessToken: session.access_token,
        refreshToken: session.refresh_token,
        expiresIn: session.expires_in,
        account: session.account,
      });
    } catch (caught) {
      // ⚠️ ٤٠١ **هنا** تعني بيانات دخول خاطئة لا جلسة منتهية: لا جلسة بعد
      // أصلًا. رسالة السيرفر هي الصحيحة، و`describeFailure` تترجم ٤٠١ إلى
      // «انتهت جلستك» لأنها كُتبت للمسارات المحمية.
      if (caught?.status === 401) {
        showAlert(caught.message, "none");
        render();
        return;
      }
      await handleFailure(caught, "تعذّر تسجيل الدخول. حاول مرة أخرى.");
    }
  });
}

/**
 * يتبنّى جلسة صادرة عن الدخول أو التسجيل، ويتابع المسار.
 *
 * مشتركة بين المسارين عمدًا: ما يلي الجلسة واحد — قراءة الاشتراك، ثم
 * تبنّي أي Runtime مثبَّت. لو كُتب مرتين لتفرّق سلوك الدخول عن التسجيل
 * عند أول تعديل.
 */
async function adoptSession({ accessToken, refreshToken, expiresIn, account }) {
  await setSession({ accessToken, refreshToken, expiresIn, account });
  state.session = await getSession();
  state.account = account ?? null;
  state.wantsRegister = false;
  state.awaitingEmailConfirmation = false;

  if (!state.account) {
    render();
    return;
  }

  await refreshSubscription();

  // إقرار طريقة البدء يخصّ هذا البريد وحده — يُقرأ عند كل دخول.
  state.planAcknowledged = await hasAcknowledgedPlan(state.account.email);

  // ⚠️ **تبديل الحساب على الجهاز نفسه لا يورّث حالة تثبيت.** التنظيف
  // يقارن بمالك الحالة المحفوظ، فيمسحها إن كانت لغير الداخل الآن.
  await reconcileInstallState(state.account.email);

  // مرحلة تثبيت محفوظة من جلسة سابقة على الجهاز نفسه.
  const resuming = await resumeInstall();

  const existing = await findRuntime();
  if (existing) {
    render();
    void adoptRuntime(existing);
    return;
  }

  render();
  if (resuming) {
    watchProgress();
  } else if (state.installStarted) {
    void watchForRuntime();
  }
}

async function doRegister(event) {
  event.preventDefault();
  clearAlert();

  const fullName = el.registerName.value.trim();
  const email = el.registerEmail.value.trim();
  const password = el.registerPassword.value;
  const confirmPassword = el.registerConfirm.value;

  if (!fullName || !email || !password) {
    showAlert("أكمل جميع الحقول للمتابعة.", "none");
    return;
  }
  if (password.length < 8) {
    showAlert("كلمة المرور يجب أن تكون ثمانية أحرف على الأقل.", "none");
    return;
  }
  // فحص التطابق هنا **وعلى السيرفر**: هذا لتجربة أسرع، وذاك لأن العميل
  // قد يُتجاوَز بطلب مباشر.
  if (password !== confirmPassword) {
    showAlert("كلمتا المرور غير متطابقتين.", "none");
    el.registerConfirm.focus();
    return;
  }

  await withBusy(el.registerSubmit, async () => {
    try {
      const result = await register({
        fullName,
        email,
        password,
        confirmPassword,
      });

      // كلمتا المرور لا تبقيان في الحقلين بعد الإرسال.
      el.registerPassword.value = "";
      el.registerConfirm.value = "";
      state.registeredEmail = result.email ?? email;

      if (result.requires_email_confirmation || !result.access_token) {
        // الحساب أُنشئ فعلًا؛ الرسالة توضّح ذلك بدل أن يبدو التسجيل فاشلًا.
        state.awaitingEmailConfirmation = true;
        render();
        return;
      }

      await adoptSession({
        accessToken: result.access_token,
        refreshToken: result.refresh_token,
        expiresIn: result.expires_in,
        account: result.account,
      });
    } catch (caught) {
      // ٤٠٩ و٤٢٢ هنا رسائل خدمة واضحة (بريد مسجَّل، كلمة مرور ضعيفة)
      // لا أخطاء جلسة.
      if (caught?.status === 409 || caught?.status === 422) {
        showAlert(caught.message, "none");
        render();
        return;
      }
      await handleFailure(caught, "تعذّر إنشاء الحساب. حاول مرة أخرى.");
    }
  });
}

function showRegister() {
  clearAlert();
  state.wantsRegister = true;
  state.awaitingEmailConfirmation = false;
  render();
  el.registerName?.focus();
}

function showLogin() {
  clearAlert();
  state.wantsRegister = false;
  state.awaitingEmailConfirmation = false;
  render();
  el.signinEmail?.focus();
}

/* =========================================================================
   طريقة البدء — نسخة عرض أكاديمية
   =========================================================================
   ⚠️ **لا بوابة دفع ولا حقول بطاقة ولا تغيير للاشتراك.** التسجيل ينشئ
   اشتراكًا تجريبيًا ٣٠ يومًا بمقعد واحد، فزرّ «ابدأ التجربة» **يقرّ
   القائم ولا ينشئ غيره**: نداءٌ ثانٍ كان سيضاعف الصفوف أو يمدّ التاريخ.
   ========================================================================= */

/**
 * يقرّ التجربة القائمة ويتابع إلى التثبيت.
 *
 * **لا طلب شبكي إطلاقًا.** الاشتراك موجود من لحظة التسجيل؛ ما ينقص هو
 * أن يرى صاحبه ما اشترك فيه ويوافق. الإقرار يُحفظ ببريده وحده.
 */
async function doStartTrial() {
  clearAlert();
  state.planAcknowledged = true;
  await acknowledgePlan(state.account?.email);
  render();
}

/*
 * ⚠️ **لا نافذة للاشتراك الكامل، ولا يجوز أن تعود.**
 *
 * كانت نافذةً تُفتح من زرّ «اشترك الآن» لتشرح أن الدفع غير مفعّل. وقد
 * ظهرت للمستخدم **دائمًا** لا عند الضغط: `.modal` أعلنت `display: grid`
 * بلا حارس `.modal[hidden]`، وقاعدة المؤلّف تغلب `[hidden]` في ورقة
 * المتصفح — فبقيت طبقةٌ سوداء فوق كل شيء، وزرّ إغلاقها يضبط `hidden`
 * بلا أثر مرئي، فبدا معطّلًا.
 *
 * البديل ليس إصلاحها: **زرّ معطّل بسمة `disabled` وملصقٌ ساكن تحته**.
 * لا طبقة تُفتح ولا تُغلق، فلا شيء يحجب الخيارين ولا شيء يعلق.
 */

/**
 * ينقل الاشتراك من الجهاز السابق إلى هذا الجهاز.
 *
 * **يفعله صاحب الحساب بنفسه** — لا مسؤول يوافق ولا طلب يُرفع. لذلك تُطلب
 * كلمة المرور من جديد: النتيجة أن GovMind يتوقف على حاسب آخر، وجلسةٌ
 * متروكة مفتوحة على جهاز عام يجب ألا تُفقد صاحبها جهازه.
 *
 * التحقق من كلمة المرور والإبطال والتفعيل كلها على السيرفر؛ هنا إرسالٌ
 * وعرض. **كلمة المرور لا تُخزَّن ولا تبقى في الحقل بعد الإرسال.**
 */
async function doReplaceDevice(event) {
  event?.preventDefault();
  clearAlert();

  const password = el.replacePassword?.value ?? "";
  if (!password) {
    showAlert("أدخل كلمة مرور حسابك للمتابعة.", "none");
    el.replacePassword?.focus();
    return;
  }

  await withBusy(el.replaceSubmit, async () => {
    try {
      const deviceId = await ensureDeviceId();
      const deviceName = await ensureDeviceName();
      const result = await replaceDevice(
        state.session.token,
        deviceId,
        deviceName,
        password,
      );
      state.subscription = result.subscription;
      render();
    } catch (caught) {
      // ٤٠١ هنا **ليست انتهاء جلسة** بل كلمة مرور خاطئة: لا يُخرَج
      // المستخدم من حسابه، وإنما يُطلب منه إعادة الإدخال.
      if (caught?.status === 401) {
        showAlert(caught.message, "none");
        el.replacePassword?.focus();
        return;
      }
      // ٤٠٩ تعني سباقًا: طلب استبدال آخر سبقه. الصورة تُحدَّث ثم تُشرح.
      if (caught?.status === 409) {
        try {
          await refreshSubscription();
        } catch {
          /* تُترك الصورة السابقة؛ الرسالة أدناه تشرح الحالة. */
        }
        showAlert(caught.message, "none");
        render();
        return;
      }
      await handleFailure(caught, "تعذّر استبدال الجهاز. حاول مرة أخرى.");
    } finally {
      // لا تبقى كلمة المرور في الحقل، نجح الاستبدال أو فشل.
      if (el.replacePassword) el.replacePassword.value = "";
    }
  });
}

async function doRefresh() {
  clearAlert();
  await withBusy(null, async () => {
    try {
      await refreshSubscription();
      render();
    } catch (caught) {
      await handleFailure(caught, "تعذّر تحديث الحالة. حاول مرة أخرى.");
    }
  });
}

async function doSignOut() {
  stopWatching();
  state.pollAbort = true;
  // حالة التثبيت تخصّ صاحبها: تُمسح مع جلسته فلا يرثها من يدخل بعده.
  await clearInstallProgress();
  await clearSession();
  state.session = null;
  state.account = null;
  state.subscription = null;
  state.download = "idle";
  state.downloadId = null;
  state.installStarted = false;
  state.openFailed = false;
  state.handoverFailure = null;
  state.activationFailure = null;
  state.runtimeTimedOut = false;
  state.planAcknowledged = false;
  // الـRuntime يخصّ الجهاز لا الجلسة، لكن عرضه بعد الخروج بلا معنى.
  state.runtime = null;
  state.handingOver = false;
  clearAlert();
  // الترحيب لا يُعاد على من رآه: الخروج ليس تثبيتًا جديدًا.
  state.welcomeSeen = true;
  state.wantsRegister = false;
  state.awaitingEmailConfirmation = false;
  render();
}

/* =========================================================================
   التنزيل
   ========================================================================= */
function stopWatching() {
  state.stopWatching?.();
  state.stopWatching = null;
}

function renderProgress(item) {
  const percent = percentOf(item);
  const received = formatBytes(item.bytesReceived);

  if (percent === null) {
    // حجم كلي مجهول: حركة مستمرة ونصّ بما نُزّل فعلًا، لا نسبة مخترعة.
    el.progressBar.dataset.indeterminate = "true";
    el.progressBar.style.removeProperty("inline-size");
    el.progress.removeAttribute("aria-valuenow");
    el.progressLabel.textContent = `نُزّل ${received}…`;
    return;
  }

  delete el.progressBar.dataset.indeterminate;
  el.progressBar.style.inlineSize = `${percent}%`;
  el.progress.setAttribute("aria-valuenow", String(percent));
  el.progressLabel.textContent =
    `${percent}٪ — ${received} من ${formatBytes(item.totalBytes)}`;
}

async function doDownload() {
  clearAlert();
  await withBusy(el.installStart, async () => {
    let link;
    try {
      const deviceId = await ensureDeviceId();

      // ⚠️ **رمز التركيب يُطلب قبل التنزيل لا بعده.** لو طُلب بعد التثبيت
      // لاحتاج المستخدم أن يعود إلى الإضافة ويضغط زرًّا آخر — والمطلوب
      // أن يكتمل كل شيء بضغطة واحدة.
      const session = await requestInstallationSession(state.session.token);
      await setInstallToken(session.token, session.expires_at);

      link = await requestInstallerUrl(state.session.token, deviceId);
    } catch (caught) {
      await clearInstallToken();
      await handleFailure(caught, "تعذّر تجهيز رابط التنزيل. حاول مرة أخرى.");
      return;
    }

    try {
      // ⚠️ الرابط يمرّ من هنا إلى المتصفح مباشرة ولا يُعرض ولا يُخزَّن.
      state.downloadId = await startDownload(link.download_url, link.file_name);
      state.downloadFileName = link.file_name;
      state.download = "running";
      // يُحفظ فورًا: النافذة تُغلق بفقد التركيز، وقد يقع ذلك بعد سطر واحد.
      await setInstallProgress({
        stage: "downloading",
        downloadId: state.downloadId,
        fileName: link.file_name,
      });
      el.progressLabel.textContent = "يبدأ التنزيل…";
      render();
      watchProgress();
    } catch (caught) {
      await handleFailure(caught, "تعذّر بدء التنزيل. حاول مرة أخرى.");
    }
  });
}

function watchProgress() {
  stopWatching();
  state.stopWatching = watchDownload(state.downloadId, {
    onProgress: renderProgress,
    onDone: () => {
      stopWatching();
      state.download = "done";
      state.installStarted = false;
      state.openFailed = false;
      void setInstallProgress({ stage: "downloaded" });
      render();
      // ⚠️ **لا استطلاع للـRuntime هنا، ولا فتح تلقائي للملف.**
      //
      // هنا كان نصف العطل الثاني: تنتهي التنزيلة فتبدأ الإضافة تنتظر
      // برنامجًا لم يُثبَّت بعد، فتعرض «جارٍ البحث» بينما الملف ما زال في
      // مجلد التنزيلات لم يفتحه أحد.
      //
      // وفتحُ الملف هنا — ولو «توفيرًا لخطوة» — تشغيلٌ صامت لملف تنفيذي
      // بلا نقرة. الانتظار يبدأ بعد أن **يضغط المستخدم «فتح ملف التثبيت»
      // ويقبل المتصفح الفتح** — انظر `doOpenInstaller`.
    },
    onFail: (message) => {
      stopWatching();
      state.download = "idle";
      state.downloadId = null;
      void clearInstallProgress();
      showAlert(message, "retry");
      render();
    },
  });
}

async function doCancelDownload() {
  stopWatching();
  if (state.downloadId !== null) await cancelDownload(state.downloadId);
  state.download = "idle";
  state.downloadId = null;
  state.installStarted = false;
  state.openFailed = false;
  await clearInstallProgress();
  showAlert("أُلغي التنزيل. يمكنك بدؤه من جديد في أي وقت.", "none");
  render();
}

/**
 * يفتح ملف المثبّت **من نقرة المستخدم**، ثم — وعلى نتيجتها وحدها — يبدأ
 * انتظار الـRuntime.
 *
 * ⚠️ **ترتيب السطور هنا هو الإصلاح، لا نصّ الزرّ.**
 *
 * 1. `openDownload` **أول سطر عمل، قبل أي `await`.** فتحُ ملف من إضافة
 *    يشترط إيماءة مستخدم، وأي انتظار قبله يُنهيها فيرفض المتصفح الفتح بلا
 *    سبب ظاهر — فيبدو الزرّ معطّلًا.
 * 2. `installStarted` لا تُضبط إلا إن **قَبِل المتصفح**. الزرّ السابق كان
 *    يضبطها على إقرار المستخدم، فتنتظر الإضافة إلى الأبد برنامجًا لم
 *    يُفتح ملفُه أصلًا.
 * 3. الرفض ليس خطأً غامضًا: يُظهَر الملف في مجلده وتُعرض خطوة واحدة
 *    باقية، **وبلا استطلاع** — لا شيء فُتح لينتظره أحد.
 *
 * ⚠️ **ولا يتخطّى هذا شيئًا في ويندوز.** الطلب يذهب إلى المتصفح ليفتح
 * ملفًا نزّله المستخدم، تمامًا كالضغط عليه في شريط التنزيلات؛ وUAC
 * وSmartScreen وSmart App Control تعمل بعده كما تعمل دائمًا.
 */
async function doOpenInstaller() {
  // ⚠️ **حارس متزامن لا `withBusy`.** `withBusy` تنتظر، والانتظار قبل
  // الفتح يُنهي إيماءة المستخدم. الفحص والضبط هنا يقعان في النقرة نفسها،
  // فنقرتان سريعتان لا تفتحان المثبّت مرتين.
  if (state.openingInstaller) return;
  state.openingInstaller = true;

  try {
    await runOpenInstaller();
  } finally {
    state.openingInstaller = false;
  }
}

async function runOpenInstaller() {
  clearAlert();

  const downloadId = state.downloadId;
  if (downloadId === null) {
    // لا ملف نعرفه: الحالة المحفوظة تعثّرت، والصحيح إعادة التنزيل لا
    // انتظار شيء لا وجود له.
    await doRestartInstall();
    return;
  }

  // ⚠️ لا `await` قبل هذا السطر. انظر أعلاه.
  const opened = await openDownload(downloadId);

  if (!opened) {
    // ⚠️ **لا استطلاع.** ولا محاولة فتح بطريقة أخرى.
    state.openFailed = true;
    state.installStarted = false;
    showInFolder(downloadId);
    render();
    return;
  }

  state.openFailed = false;
  state.installStarted = true;
  state.runtimeTimedOut = false;
  state.handoverFailure = null;
  state.activationFailure = null;
  state.pollAbort = false;
  await setInstallProgress({ stage: "installing" });
  render();
  void watchForRuntime();
}

/**
 * «تحقق من التثبيت»: يبحث عن الـRuntime الآن، بمهلة جديدة.
 *
 * يُستعمل من شاشة تعذّر الفتح ومن شاشة التشخيص معًا: في كلتيهما فتح
 * المستخدمُ الملف بنفسه من المجلد، فالمطلوب واحد.
 */
function doRetryRuntime() {
  clearAlert();
  state.runtimeTimedOut = false;
  state.handoverFailure = null;
  state.activationFailure = null;
  state.pollAbort = false;
  // فتحه المستخدم من المجلد بنفسه — وهو ما يجعل الانتظار مشروعًا هنا.
  state.installStarted = true;
  state.openFailed = false;
  void setInstallProgress({ stage: "installing" });
  render();
  void watchForRuntime();
}

/**
 * يعيد محاولة تسليم رمز التركيب بعد فشلٍ في التسليم أو رفضٍ للتفعيل.
 *
 * **يُصدر رمزًا جديدًا عند الحاجة:** رمز المحاولة السابقة مُحي، وإجبار
 * المستخدم على إعادة تنزيل مثبّت يملكه عقوبة بلا سبب.
 */
async function doRetryHandover() {
  clearAlert();
  state.handoverFailure = null;
  state.activationFailure = null;
  state.runtimeTimedOut = false;
  state.pollAbort = false;
  render();

  // الاشتراك قد يكون تغيّر (استُبدل الجهاز من حاسب آخر مثلًا): تُقرأ
  // صورته من جديد قبل محاولة ثانية تفشل للسبب نفسه.
  try {
    await refreshSubscription();
  } catch {
    /* تُترك الصورة السابقة؛ المحاولة أدناه تكشف الحقيقة على أي حال. */
  }

  const found = await findRuntime();
  if (!found) {
    // لا Runtime: نعود إلى الانتظار لا إلى شاشة فشل ساكنة.
    render();
    void watchForRuntime();
    return;
  }
  await adoptRuntime(found);
}

/** يبدأ التنزيل من جديد بعد أن تعذّر التثبيت. */
async function doRestartInstall() {
  clearAlert();
  stopWatching();
  state.pollAbort = true;
  state.download = "idle";
  state.downloadId = null;
  state.downloadFileName = null;
  state.installStarted = false;
  state.openFailed = false;
  state.handoverFailure = null;
  state.activationFailure = null;
  state.runtimeTimedOut = false;
  await clearInstallProgress();
  render();
}

/* =========================================================================
   الـRuntime: الاكتشاف وتسليم الرمز ومتابعة التجهيز
   ========================================================================= */

/**
 * ينتظر ظهور الـRuntime بعد أن يفتح المستخدم المثبّت، ثم يسلّمه الرمز.
 *
 * **الانتظار طويل عمدًا** (١٥ دقيقة): يشمل فتح الملف، وموافقة ويندوز،
 * وخطوات المثبّت. الاستسلام قبل ذلك يترك المستخدم أمام شاشة انتظار بينما
 * التثبيت يعمل.
 */
async function watchForRuntime() {
  const found = await waitForRuntime({
    timeoutMs: RUNTIME_WAIT_MS,
    shouldStop: () => state.pollAbort,
    onTick: (elapsed) => {
      if (!el.awaitingLabel) return;
      const minutes = Math.floor(elapsed / 60000);
      el.awaitingLabel.textContent =
        minutes >= 1
          ? `جارٍ البحث عن GovMind على هذا الجهاز… (${minutes} د)`
          : "جارٍ البحث عن GovMind على هذا الجهاز…";
    },
  });

  if (!found) {
    // ⚠️ **لا يُترك المستخدم أمام حركة مستمرة إلى الأبد.**
    // انتهت المهلة (أو أُوقف الاستطلاع): تُعرض شاشة تشخيص تسمّي الأسباب
    // المحتملة — ومنها منع ويندوز للبرنامج — ومعها زر إعادة محاولة.
    if (!state.pollAbort) {
      state.runtimeTimedOut = true;
      if (el.installHelpMessage) {
        el.installHelpMessage.textContent =
          "لم يبدأ GovMind بعد. تأكد من إكمال المثبّت وأن Windows لم يمنعه، " +
          "ثم أعد المحاولة.";
      }
      render();
    }
    return;
  }
  await adoptRuntime(found);
}

/** يتبنّى Runtime عُثر عليه: يحفظ منفذه ويكمل المسار. */
async function adoptRuntime({ port, health }) {
  state.runtimePort = port;
  state.runtime = health;
  await setRuntimePort(port);
  render();

  if (health.needs_activation) {
    await deliverToken();
    return;
  }
  void followRuntime();
}

/**
 * يسلّم رمز التركيب إلى الـRuntime.
 *
 * ⚠️ **يُمحى الرمز بعد المحاولة، نجحت أو فشلت.** رمزٌ لمرة واحدة يبقى في
 * التخزين بعد استهلاكه سرٌّ بلا فائدة، وبقاؤه بعد الفشل يجعل الإضافة
 * تعيد إرساله إلى ما لا نهاية.
 */
async function deliverToken() {
  // **يُصدر رمزًا جديدًا عند الحاجة بدل أن يتوقّف.**
  //
  // الحالة الواقعية: Runtime مثبَّت وينتظر التفعيل، والإضافة بلا رمز —
  // أُعيد تثبيتها، أو انتهت مهلة الرمز أثناء التثبيت. إجبار المستخدم على
  // إعادة تنزيل مثبّت يملكه أصلًا عقوبة بلا سبب؛ الرمز وحده هو الناقص.
  if (!isSessionUsable(state.session)) {
    // لا يمكن إصدار رمز بلا جلسة. الشاشة تعود إلى الدخول من تلقائها.
    return;
  }

  let token = await getInstallToken();
  if (!token) {
    try {
      const session = await requestInstallationSession(state.session.token);
      await setInstallToken(session.token, session.expires_at);
      token = session.token;
    } catch (caught) {
      // ⚠️ **تعذّر إصدار جلسة التركيب — لا تعذّر تفعيل الجهاز.** الرمز لم
      // يصدر أصلًا، فلا شيء وصل الـRuntime ليُرفض.
      state.handoverFailure =
        "تعذّر تجهيز رمز التركيب لهذا الجهاز. أعد المحاولة.";
      state.handingOver = false;
      render();
      return;
    }
  }

  state.handingOver = true;
  state.handoverFailure = null;
  state.activationFailure = null;
  clearAlert();
  render();

  try {
    await handOverToken(state.runtimePort, token);
  } catch (caught) {
    // ⚠️ **الحالتان تُفرَّقان لأن إجراء المستخدم يختلف.**
    //
    // `ActivationFailedError` تعني أن الرمز وصل ورفضه الخادم — اشتراك لا
    // يسمح، أو جهاز آخر — ورسالتُه هي الصحيحة، والإجراء تجديدٌ أو استبدال.
    // و`HandoverFailedError` تعني أن الرمز لم يصل: الـRuntime لا يستجيب،
    // أو تعذّر عليه بلوغ الخدمة أو حفظ الربط. والإجراء إكمال التثبيت.
    if (caught instanceof ActivationFailedError) {
      state.activationFailure = caught.message;
    } else if (caught instanceof HandoverFailedError) {
      state.handoverFailure = caught.message;
    } else {
      state.handoverFailure =
        "لم يصل رمز التركيب إلى GovMind على هذا الجهاز. تأكد من اكتمال " +
        "التثبيت ثم أعد المحاولة.";
    }
    // الرمز يُمحى في `finally` أدناه، والشاشة تعرض السبب بلا شريط تقدّم.
    await clearInstallToken();
    state.handingOver = false;
    render();
    return;
  } finally {
    await clearInstallToken();
    state.handingOver = false;
  }

  void followRuntime();
}

/** يتابع تقدّم الـRuntime حتى يصير جاهزًا أو يتوقف. */
async function followRuntime() {
  for (;;) {
    if (state.pollAbort || state.runtimePort === null) return;

    const found = await findRuntime();
    if (!found) {
      // اختفى الـRuntime (أُعيد تشغيله أو أُغلق): نعود إلى انتظاره.
      state.runtime = null;
      render();
      return;
    }

    state.runtime = found.health;
    state.runtimePort = found.port;
    render();

    if (found.health.is_ready) return;
    if (found.health.phase === "blocked" || found.health.phase === "error") {
      showAlert(found.health.message, "retry");
      return;
    }

    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

/* =========================================================================
   المظهر — خياران: فاتح وداكن
   =========================================================================
   الاختيار في `localStorage` لا في `chrome.storage.local`: القراءة متزامنة
   فيضبطه `theme-init.js` قبل أول رسم بلا وميض. ولا صلاحية جديدة لأيّهما.

   ⚠️ **خيار «تلقائي» أُزيل نهائيًا** من القائمة والتخزين والأيقونات، كما
   في الموقع تمامًا. كان يفرض أحد أمرين: أيقونةَ حاسوب في ترويسة برنامج
   ليس عن الحواسيب، أو أيقونةً لا تدلّ على الخيار المحفوظ. والاختيار الآن
   صريح ولا يتغيّر تحت المستخدم عند غروب الشمس.
   ========================================================================= */
const THEME_KEY = "govagent.theme";

/** أيقونتان لا ثلاث: الشمس والقمر. **ولا أيقونة حاسوب في أي مكان.** */
const THEME_ICONS = {
  light:
    "M10 6a4 4 0 1 0 0 8 4 4 0 0 0 0-8m0 1.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5M10 1.5a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 1.5m0 14a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 15.5M18.5 10a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5a.75.75 0 0 1 .75.75m-14 0a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5a.75.75 0 0 1 .75.75m11.5-6a.75.75 0 0 1 0 1.06l-1.06 1.06a.75.75 0 1 1-1.06-1.06L14.94 4a.75.75 0 0 1 1.06 0M6.62 13.38a.75.75 0 0 1 0 1.06L5.56 15.5A.75.75 0 0 1 4.5 14.44l1.06-1.06a.75.75 0 0 1 1.06 0m9.38 2.12a.75.75 0 0 1-1.06 0l-1.06-1.06a.75.75 0 0 1 1.06-1.06l1.06 1.06a.75.75 0 0 1 0 1.06M6.62 6.62a.75.75 0 0 1-1.06 0L4.5 5.56A.75.75 0 0 1 5.56 4.5l1.06 1.06a.75.75 0 0 1 0 1.06",
  dark:
    "M16.3 12.6a6.6 6.6 0 0 1-8.9-8.9.75.75 0 0 0-.98-.98 8.1 8.1 0 1 0 10.86 10.86.75.75 0 0 0-.98-.98M10 16.6a6.6 6.6 0 0 1-4.6-11.3 8.1 8.1 0 0 0 9.9 9.9A6.57 6.57 0 0 1 10 16.6",
};

const THEME_LABELS = { light: "فاتح", dark: "داكن" };

/** الافتراضي حين لا اختيار محفوظ — ومآلُ كل قيمة قديمة. */
const DEFAULT_THEME = "light";

/**
 * يقرأ الخيار المحفوظ، **ويهاجر القيم القديمة إلى «فاتح»**.
 *
 * تركيبات قائمة تحمل `"system"` أو `"auto"` في تخزينها من نسخة سابقة.
 * إهمالها كان سيترك الشرط `=== "dark"` كاذبًا فتُعرض الواجهة فاتحة بينما
 * تُعلَّم القائمة بخيار لم يعد موجودًا. فتُقرأ هنا على أنها «فاتح» —
 * والكتابة عند أول تغيير تمحوها من التخزين.
 */
function readThemeChoice() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === "dark" ? "dark" : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

function applyThemeChoice(choice) {
  // أي قيمة غير `dark` — بما فيها `system` القديمة — تعني «فاتح».
  const resolved = choice === "dark" ? "dark" : DEFAULT_THEME;
  document.documentElement.dataset.theme = resolved;

  if (el.themeIcon) {
    // `textContent` لا يصلح لمسار SVG، والمسارات ثابتة في الكود لا من الشبكة.
    el.themeIcon.replaceChildren();
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("fill", "currentColor");
    path.setAttribute("d", THEME_ICONS[resolved]);
    el.themeIcon.append(path);
  }
  if (el.themeTrigger) {
    el.themeTrigger.title = `المظهر: ${THEME_LABELS[resolved]}`;
    el.themeTrigger.setAttribute("aria-label", `المظهر: ${THEME_LABELS[resolved]}`);
  }
  for (const item of document.querySelectorAll("[data-theme-choice]")) {
    item.setAttribute(
      "aria-checked",
      String(item.dataset.themeChoice === resolved),
    );
  }
}

function setThemeChoice(choice) {
  const resolved = choice === "dark" ? "dark" : DEFAULT_THEME;
  try {
    localStorage.setItem(THEME_KEY, resolved);
  } catch {
    /* تجاهل: الوضع مطبَّق على النافذة ولو لم يُحفظ. */
  }
  applyThemeChoice(resolved);
}

function closeThemeMenu() {
  if (!el.themeMenu) return;
  el.themeMenu.hidden = true;
  el.themeTrigger?.setAttribute("aria-expanded", "false");
}

/* =========================================================================
   الربط بالأحداث
   ========================================================================= */
el.welcomeNext?.addEventListener("click", async () => {
  state.welcomeSeen = true;
  await setWelcomeSeen();
  render();
});

el.signinForm?.addEventListener("submit", doSignIn);
el.registerForm?.addEventListener("submit", doRegister);
el.goRegister?.addEventListener("click", showRegister);
el.goLogin?.addEventListener("click", showLogin);
el.confirmEmailLogin?.addEventListener("click", showLogin);
el.planTrialStart?.addEventListener("click", doStartTrial);
// ⚠️ **لا مستمع لـ`plan-paid-start`.** السمة `disabled` تمنع النقر في
// المتصفح، وغياب المستمع يجعل المنع مضاعفًا لا معتمدًا على شرط.
// ⚠️ **`chrome.downloads.open` تُستدعى من داخل هذا المستمع مباشرة.**
// إيماءة المستخدم لا تنجو من `await` قبلها — انظر `doOpenInstaller`.
el.readyOpen?.addEventListener("click", doOpenInstaller);
el.openFailedCheck?.addEventListener("click", doRetryRuntime);
el.helpRetry?.addEventListener("click", doRetryRuntime);
el.helpRestart?.addEventListener("click", doRestartInstall);
el.handoverRetry?.addEventListener("click", doRetryHandover);
el.handoverRestart?.addEventListener("click", doRestartInstall);
el.activationRetry?.addEventListener("click", doRetryHandover);
el.replaceForm?.addEventListener("submit", doReplaceDevice);
el.installStart?.addEventListener("click", doDownload);
el.downloadCancel?.addEventListener("click", doCancelDownload);

for (const button of document.querySelectorAll("[data-signout]")) {
  button.addEventListener("click", doSignOut);
}
for (const button of document.querySelectorAll("[data-refresh]")) {
  button.addEventListener("click", doRefresh);
}

el.alertAction?.addEventListener("click", () => {
  const action = el.alertAction.dataset.action;
  clearAlert();
  if (action === "signin") {
    void doSignOut();
    return;
  }
  void doRefresh();
});

el.themeTrigger?.addEventListener("click", () => {
  const willOpen = el.themeMenu.hidden;
  el.themeMenu.hidden = !willOpen;
  el.themeTrigger.setAttribute("aria-expanded", String(willOpen));
});

for (const item of document.querySelectorAll("[data-theme-choice]")) {
  item.addEventListener("click", () => {
    setThemeChoice(item.dataset.themeChoice);
    closeThemeMenu();
  });
}

document.addEventListener("mousedown", (event) => {
  if (!el.themeRoot?.contains(event.target)) closeThemeMenu();
});

// ⚠️ لا مستمع لـ`prefers-color-scheme`: المظهر اختيار صريح لا يتبع الجهاز.

// النافذة تُغلق بفقد التركيز؛ إيقاف المؤقّت يمنع مؤقّتًا معلّقًا بلا نافذة.
// ⚠️ **إظهار الملف في المجلد، لا تشغيله.** لا يوجد في هذه الإضافة أي
// استدعاء يشغّل ملفًا تنفيذيًا، ولا يجوز أن يوجد.
for (const button of [
  el.awaitingShow,
  el.readyShow,
  el.helpShow,
  el.openFailedShow,
]) {
  button?.addEventListener("click", () => {
    if (state.downloadId !== null) showInFolder(state.downloadId);
  });
}

el.awaitingHelp?.addEventListener("click", () => {
  clearAlert();
  state.runtimeTimedOut = true;
  render();
});

el.installedOpen?.addEventListener("click", () => {
  if (state.runtimePort !== null) void openGovMind(state.runtimePort);
});

/**
 * يوقف كل عمل خلفي: متابعة التنزيل واستطلاع الـRuntime.
 *
 * مُصدَّرة لأن لها مستدعيَين: إغلاق النافذة، وتفكيك النافذة في الاختبارات.
 * حلقةُ استطلاع تبقى بعد ذهاب نافذتها تعيد الرسم على مستندٍ لم يعد لها.
 */
export function stopBackgroundWork() {
  stopWatching();
  state.pollAbort = true;
}

// النافذة تُغلق بفقد التركيز؛ إيقاف الاستطلاع يمنع حلقة بلا نافذة.
window.addEventListener("unload", stopBackgroundWork);

/**
 * يستأنف مرحلة التثبيت المحفوظة بدل أن يبدأها من جديد.
 *
 * ⚠️ **هذا ما يمنع تكرار كل شيء.** نافذة الإضافة تُغلق بمجرد أن تفقد
 * التركيز — وهو ما يحدث حتمًا حين يفتح المستخدم المثبّت. فلولا الاستئناف
 * لعادت النافذة إلى «نزّل GovMind»، فيبدأ المستخدم تنزيلًا ثانيًا لملف
 * يملكه، ويُطلب **رمز تركيب ثالث** بلا داعٍ، وتُترك جلسات تركيب مهجورة.
 *
 * الحقيقة تُقرأ من `chrome.downloads` لا من المخزون وحده: التنزيل قد يكون
 * اكتمل أو أُلغي أو حُذف ملفه والنافذة مغلقة.
 *
 * @returns {Promise<boolean>} هل استُؤنف تنزيل جارٍ يحتاج متابعة؟
 */
async function resumeInstall() {
  const saved = await getInstallProgress();

  // ⚠️ **بلا `downloadId` صالح لا يُستأنف شيء ولا يُستطلع الـRuntime.**
  // مرحلةٌ متقدّمة بلا تنزيل تحتها حالةٌ لا معنى لها؛ تُمسح ويُبدأ نظيفًا.
  if (saved.stage === "idle" || !Number.isInteger(saved.downloadId)) {
    if (saved.stage !== "idle") await clearInstallProgress();
    return false;
  }

  state.downloadFileName = saved.fileName;

  const item = await queryDownload(saved.downloadId);
  if (!item) {
    // اختفى من سجل التنزيلات (مُسح أو ملف تعريف آخر): نبدأ نظيفًا.
    await clearInstallProgress();
    return false;
  }

  if (item.state === "in_progress") {
    state.downloadId = saved.downloadId;
    state.download = "running";
    return true;
  }

  if (item.state === "complete") {
    state.downloadId = saved.downloadId;
    state.download = "done";
    // **لا يُعاد تنزيل ملف مكتمل.** يُستأنف عند شاشة الفتح، أو عند انتظار
    // الـRuntime إن كان المتصفح قد فتح الملف فعلًا في جلسة سابقة.
    //
    // ⚠️ `installing` تُكتب في `doOpenInstaller` **بعد** أن يقبل المتصفح
    // الفتح، وفي `doRetryRuntime` بعد أن يفتحه المستخدم من المجلد. فلا
    // تُستأنف شاشةُ انتظار على نيّة لم تتحقّق.
    state.installStarted = saved.stage === "installing";
    return false;
  }

  // أُلغي أو انقطع: لا يُستأنف، والشاشة تعود إلى التثبيت برسالة.
  await clearInstallProgress();
  return false;
}

/* =========================================================================
   الإقلاع
   ========================================================================= */
export async function boot() {
  applyThemeChoice(readThemeChoice());
  await pruneLegacyKeys();

  // **الإقلاع يبني الحالة من الصفر.** كل ما دون الجلسة مشتقٌّ من الشبكة
  // أو من الجهاز، فبقاؤه من تشغيل سابق يجعل النافذة تعرض اشتراكًا أو
  // مرحلة تجهيز لحسابٍ آخر.
  state.subscription = null;
  state.runtime = null;
  state.runtimePort = null;
  state.handingOver = false;
  state.download = "idle";
  state.downloadId = null;
  state.downloadFileName = null;
  state.wantsRegister = false;
  state.awaitingEmailConfirmation = false;
  state.planAcknowledged = false;
  state.installStarted = false;
  state.openFailed = false;
  state.handoverFailure = null;
  state.activationFailure = null;
  state.runtimeTimedOut = false;
  state.pollAbort = false;
  state.booting = true;

  state.welcomeSeen = await getWelcomeSeen();
  state.session = await getSession();

  if (isSessionUsable(state.session)) {
    state.account = state.session.account ?? null;
    try {
      if (state.account) {
        await refreshSubscription();
      }
    } catch (caught) {
      await handleFailure(caught, "تعذّر قراءة حالة اشتراكك.");
      return render();
    }
  } else if (state.session) {
    // رمز موجود لكن مدته انتهت: يُمسح فورًا بدل أن يُرسل فيُرفض بـ٤٠١.
    await clearSession();
    state.session = null;
  }

  if (state.account) await updateAccount(state.account);

  // ⚠️ **لا يُلمس الـRuntime قبل تسجيل الدخول.** حالته لا تعني شيئًا لمن لم
  // يسجّل دخوله، وتسليم رمز تركيب يحتاج جلسةً لإصداره — فمحاولته بلا جلسة
  // تسقط على قيمة غير موجودة.
  if (!state.account) {
    state.booting = false;
    return render();
  }

  // إقرار طريقة البدء محفوظ ببريد صاحبه: من أقرّ لا يُسأل مرة أخرى، ومن
  // دخل بحساب آخر على الجهاز نفسه يُسأل كما يجب.
  state.planAcknowledged = await hasAcknowledgedPlan(state.account.email);

  // ⚠️ **تنظيف الحالة الموروثة قبل أي شيء يُرسم أو يُستطلع.**
  // حالةٌ خلّفتها نسخة معطوبة، أو تخصّ حسابًا آخر، أو رمزٌ انتهى: تُمسح
  // هنا فلا تصل إلى `resolveStep` فترسم تقدّمًا لا وجود له.
  await reconcileInstallState(state.account.email);

  // مرحلة التثبيت المحفوظة **قبل** أي لمسٍ للـRuntime.
  const resuming = await resumeInstall();

  // Runtime مثبَّت من قبل؟ حالته تسبق كل ما يخصّ المثبّت: من ثبّت البرنامج
  // لا يُعرض له «نزّل المثبّت» في كل مرة يفتح فيها الإضافة.
  //
  // ⚠️ **فحص واحد بسقف ثانية، وكل المنافذ معًا.** غيابه هو الحالة
  // الطبيعية لأول تثبيت، لا خطأ يستحق انتظارًا.
  const existing = await findRuntime();
  state.booting = false;

  if (existing) {
    state.runtimePort = existing.port;
    state.runtime = existing.health;
    render();

    // ⚠️ **تسليم الرمز فعلٌ لا يبدأ من تلقائه عند الإقلاع.**
    //
    // كان الإقلاع يسلّم الرمز لأي Runtime يقول `needs_activation` —
    // فيُصدر جلسة تركيب ويعرض «جارٍ تفعيل هذا الجهاز» بلا أن يطلب
    // المستخدم شيئًا. الآن لا يقع ذلك إلا لمن أعلن أنه بدأ التثبيت.
    if (state.installStarted) {
      if (existing.health.needs_activation) {
        void deliverToken();
      } else if (!existing.health.is_ready) {
        void followRuntime();
      }
    } else if (!existing.health.is_ready) {
      // Runtime موجود لكن غير جاهز ولم يبدأ المستخدم شيئًا: يُتابَع بصمت
      // ليُلتقط جهوزه، بلا شاشة تقدّم عن عملية ليست له.
      void followRuntime();
    }
    return render();
  }

  if (resuming) {
    // تنزيل ما زال جاريًا: تُستأنف متابعة تقدّمه، **بلا طلب رابط جديد**.
    render();
    watchProgress();
    return render();
  }

  // ⚠️ **الاستطلاع يُستأنف فقط لمن أعلن أنه بدأ التثبيت.** من نافذته
  // أُغلقت وهو عند تعليمات الفتح يعود إليها، لا إلى شاشة بحث دوّارة.
  if (state.installStarted) {
    render();
    void watchForRuntime();
    return render();
  }

  return render();
}

/**
 * إقلاع واحد لا اثنان.
 *
 * الوعد يُصدَّر بدل استدعاء `boot()` مرة هنا ومرة في الاختبار: إقلاعان
 * متزامنان يقرآن التخزين ويكتبان الحالة معًا، فتصير النتيجة تابعة لأيّهما
 * سبق. الاختبار ينتظر هذا الوعد نفسه الذي تنتظره النافذة.
 */
export const ready = boot();
