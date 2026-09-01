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
 * - **لا تشغّل ملف `.exe`**؛ لا يوجد في الشيفرة استدعاء يفعل ذلك.
 * - لا تطلب من المستخدم رابطًا ولا مفتاحًا.
 *
 * **القرار في مكان واحد:** `lib/steps.js` دالة نقية تقول أي شاشة تُعرض،
 * وهذا الملف يجمع الحالة ويعرض ما تقوله. لا شرط تدفّق مكرَّر هنا.
 */

import { RUNTIME_WAIT_MS } from "./config.js";
import {
  activateDevice,
  fetchSubscription,
  login,
  requestInstallationSession,
  requestInstallerUrl,
  verifyDevice,
} from "./lib/api.js";
import { ensureDeviceId, ensureDeviceName } from "./lib/device.js";
import {
  cancelDownload,
  formatBytes,
  percentOf,
  showInFolder,
  startDownload,
  watchDownload,
} from "./lib/download.js";
import { actionLabel, describeFailure } from "./lib/errors.js";
import {
  ActivationFailedError,
  findRuntime,
  handOverToken,
  openGovMind,
  waitForRuntime,
} from "./lib/runtime.js";
import {
  clearInstallToken,
  clearSession,
  getInstallToken,
  getRuntimePort,
  getSession,
  setInstallToken,
  setRuntimePort,
  getWelcomeSeen,
  isSessionUsable,
  pruneLegacyKeys,
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

  blockedTitle: document.getElementById("blocked-title"),
  blockedMessage: document.getElementById("blocked-message"),
  blockedFacts: document.getElementById("blocked-facts"),

  deviceTakenMessage: document.getElementById("device-taken-message"),
  deviceTakenFacts: document.getElementById("device-taken-facts"),

  activateFacts: document.getElementById("activate-facts"),
  activateSubmit: document.getElementById("activate-submit"),

  installFacts: document.getElementById("install-facts"),
  installStart: document.getElementById("install-start"),

  progress: document.getElementById("progress"),
  progressBar: document.getElementById("progress-bar"),
  progressLabel: document.getElementById("progress-label"),
  downloadCancel: document.getElementById("download-cancel"),

  awaitingFileName: document.getElementById("awaiting-file-name"),
  awaitingLabel: document.getElementById("awaiting-label"),
  awaitingShow: document.getElementById("awaiting-show"),
  awaitingRetry: document.getElementById("awaiting-retry"),

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
  /** يوقف استطلاع الـRuntime عند إغلاق النافذة. */
  pollAbort: false,
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
  if (step === STEPS.ACTIVATE) renderActivate();
  if (step === STEPS.INSTALL) renderInstall();
  if (step === STEPS.AWAITING_RUNTIME) {
    el.awaitingFileName.textContent = state.downloadFileName || "المثبّت";
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
    "اشتراكك لا يسمح باستخدام الخدمة حاليًا. راجع مسؤول النظام في جهتك.";
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
}

function renderActivate() {
  const subscription = state.subscription ?? {};
  renderFacts(el.activateFacts, [
    ["الحساب", state.account?.email],
    ["حالة الاشتراك", STATUS_LABELS[subscription.status] ?? ""],
    ["ينتهي في", formatDate(subscription.expires_at)],
  ]);
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
    ["الجهاز", subscription.device?.device_name],
    ["حالة الاشتراك", STATUS_LABELS[subscription.status] ?? ""],
    ["ينتهي في", formatDate(subscription.expires_at)],
  ]);
}

/* =========================================================================
   معالجة الفشل
   ========================================================================= */
async function handleFailure(caught, fallback) {
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
      await setSession({
        accessToken: session.access_token,
        refreshToken: session.refresh_token,
        expiresIn: session.expires_in,
        account: session.account,
      });
      state.session = await getSession();
      state.account = session.account ?? null;
      // كلمة المرور تُمحى من الحقل فور نجاح الدخول: النافذة قد تبقى مفتوحة.
      el.signinPassword.value = "";

      if (state.account) {
        await refreshSubscription();
        // Runtime مثبَّت وينتظر التفعيل؟ يُتبنّى فور الدخول بلا ضغطة.
        const existing = await findRuntime();
        if (existing) {
          render();
          void adoptRuntime(existing);
          return;
        }
      }
      render();
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

async function doActivate() {
  clearAlert();
  await withBusy(el.activateSubmit, async () => {
    try {
      const deviceId = await ensureDeviceId();
      const deviceName = await ensureDeviceName();
      state.subscription = await activateDevice(
        state.session.token,
        deviceId,
        deviceName,
      );
      render();
    } catch (caught) {
      // ٤٠٩ هنا تعني «سبقك جهاز آخر»: تُحدَّث الصورة لتُعرض شاشته الصحيحة.
      if (caught?.status === 409) {
        try {
          await refreshSubscription();
        } catch {
          /* تُترك الصورة السابقة؛ الرسالة أدناه تشرح الحالة. */
        }
      }
      await handleFailure(caught, "تعذّر تفعيل الجهاز. حاول مرة أخرى.");
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
  await clearSession();
  state.session = null;
  state.account = null;
  state.subscription = null;
  state.download = "idle";
  state.downloadId = null;
  // الـRuntime يخصّ الجهاز لا الجلسة، لكن عرضه بعد الخروج بلا معنى.
  state.runtime = null;
  state.handingOver = false;
  clearAlert();
  // الترحيب لا يُعاد على من رآه: الخروج ليس تثبيتًا جديدًا.
  state.welcomeSeen = true;
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
      render();
      // المثبّت على القرص: من الآن ننتظر أن يفتحه المستخدم فيظهر الـRuntime.
      void watchForRuntime();
    },
    onFail: (message) => {
      stopWatching();
      state.download = "idle";
      state.downloadId = null;
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
  showAlert("أُلغي التنزيل. يمكنك بدؤه من جديد في أي وقت.", "none");
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

  if (!found) return;
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
      await handleFailure(caught, "تعذّر تجهيز رمز التركيب. أعد المحاولة.");
      return;
    }
  }

  state.handingOver = true;
  clearAlert();
  render();

  try {
    await handOverToken(state.runtimePort, token);
  } catch (caught) {
    const message =
      caught instanceof ActivationFailedError
        ? caught.message
        : "تعذّر تفعيل هذا الجهاز. أعد المحاولة.";
    showAlert(message, "retry");
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
   المظهر — ثلاثة خيارات، في الإضافة وحدها
   =========================================================================
   الاختيار في `localStorage` لا في `chrome.storage.local`: القراءة متزامنة
   فيضبطه `theme-init.js` قبل أول رسم بلا وميض. ولا صلاحية جديدة لأيّهما.
   ========================================================================= */
const THEME_KEY = "govagent.theme";

const THEME_ICONS = {
  light:
    "M10 6a4 4 0 1 0 0 8 4 4 0 0 0 0-8m0 1.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5M10 1.5a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 1.5m0 14a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 15.5M18.5 10a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5a.75.75 0 0 1 .75.75m-14 0a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5a.75.75 0 0 1 .75.75m11.5-6a.75.75 0 0 1 0 1.06l-1.06 1.06a.75.75 0 1 1-1.06-1.06L14.94 4a.75.75 0 0 1 1.06 0M6.62 13.38a.75.75 0 0 1 0 1.06L5.56 15.5A.75.75 0 0 1 4.5 14.44l1.06-1.06a.75.75 0 0 1 1.06 0m9.38 2.12a.75.75 0 0 1-1.06 0l-1.06-1.06a.75.75 0 0 1 1.06-1.06l1.06 1.06a.75.75 0 0 1 0 1.06M6.62 6.62a.75.75 0 0 1-1.06 0L4.5 5.56A.75.75 0 0 1 5.56 4.5l1.06 1.06a.75.75 0 0 1 0 1.06",
  dark:
    "M16.3 12.6a6.6 6.6 0 0 1-8.9-8.9.75.75 0 0 0-.98-.98 8.1 8.1 0 1 0 10.86 10.86.75.75 0 0 0-.98-.98M10 16.6a6.6 6.6 0 0 1-4.6-11.3 8.1 8.1 0 0 0 9.9 9.9A6.57 6.57 0 0 1 10 16.6",
  system:
    "M3.5 4.25c0-.97.78-1.75 1.75-1.75h9.5c.97 0 1.75.78 1.75 1.75v7.5c0 .97-.78 1.75-1.75 1.75h-3.5v1.75h2a.75.75 0 0 1 0 1.5h-6.5a.75.75 0 0 1 0-1.5h2V13.5h-3.5a1.75 1.75 0 0 1-1.75-1.75z",
};

const THEME_LABELS = { light: "فاتح", dark: "داكن", system: "تلقائي" };

function readThemeChoice() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

function systemPrefersDark() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function applyThemeChoice(choice) {
  const resolved =
    choice === "system" ? (systemPrefersDark() ? "dark" : "light") : choice;
  document.documentElement.dataset.theme = resolved;

  if (el.themeIcon) {
    // `textContent` لا يصلح لمسار SVG، والمسارات ثابتة في الكود لا من الشبكة.
    el.themeIcon.replaceChildren();
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("fill", "currentColor");
    path.setAttribute("d", THEME_ICONS[choice]);
    el.themeIcon.append(path);
  }
  if (el.themeTrigger) {
    el.themeTrigger.title = `المظهر: ${THEME_LABELS[choice]}`;
    el.themeTrigger.setAttribute("aria-label", `المظهر: ${THEME_LABELS[choice]}`);
  }
  for (const item of document.querySelectorAll("[data-theme-choice]")) {
    item.setAttribute("aria-checked", String(item.dataset.themeChoice === choice));
  }
}

function setThemeChoice(choice) {
  try {
    localStorage.setItem(THEME_KEY, choice);
  } catch {
    /* تجاهل: الوضع مطبَّق على النافذة ولو لم يُحفظ. */
  }
  applyThemeChoice(choice);
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
el.activateSubmit?.addEventListener("click", doActivate);
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

if (typeof window.matchMedia === "function") {
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (readThemeChoice() === "system") applyThemeChoice("system");
    });
}

// النافذة تُغلق بفقد التركيز؛ إيقاف المؤقّت يمنع مؤقّتًا معلّقًا بلا نافذة.
el.awaitingShow?.addEventListener("click", () => {
  if (state.downloadId !== null) showInFolder(state.downloadId);
});

el.awaitingRetry?.addEventListener("click", () => {
  clearAlert();
  // Runtime موجود لكنه ينتظر التفعيل: أعد التسليم بدل إعادة التنزيل.
  if (state.runtime?.needs_activation && state.runtimePort !== null) {
    void deliverToken();
    return;
  }
  state.download = "idle";
  state.downloadId = null;
  render();
});

el.installedOpen?.addEventListener("click", () => {
  if (state.runtimePort !== null) void openGovMind(state.runtimePort);
});

window.addEventListener("unload", () => {
  stopWatching();
  // النافذة تُغلق بفقد التركيز؛ إيقاف الاستطلاع يمنع حلقة بلا نافذة.
  state.pollAbort = true;
});

/* =========================================================================
   الإقلاع
   ========================================================================= */
export async function boot() {
  applyThemeChoice(readThemeChoice());
  await pruneLegacyKeys();

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
  if (!state.account) return render();

  // Runtime مثبَّت من قبل؟ حالته تسبق كل ما يخصّ المثبّت: من ثبّت البرنامج
  // لا يُعرض له «نزّل المثبّت» في كل مرة يفتح فيها الإضافة.
  const existing = await findRuntime();
  if (existing) {
    state.runtimePort = existing.port;
    state.runtime = existing.health;
    render();
    if (existing.health.needs_activation) {
      void deliverToken();
    } else if (!existing.health.is_ready) {
      void followRuntime();
    }
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
