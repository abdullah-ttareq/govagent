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

import {
  activateDevice,
  fetchSubscription,
  login,
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
  clearSession,
  getSession,
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

  doneFileName: document.getElementById("done-file-name"),
  doneShow: document.getElementById("done-show"),
  doneRestart: document.getElementById("done-restart"),

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
  if (step === STEPS.DONE) {
    el.doneFileName.textContent = state.downloadFileName || "المثبّت";
  }
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

      if (state.account) await refreshSubscription();
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
      link = await requestInstallerUrl(state.session.token, deviceId);
    } catch (caught) {
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

el.doneShow?.addEventListener("click", () => {
  if (state.downloadId !== null) showInFolder(state.downloadId);
});

el.doneRestart?.addEventListener("click", () => {
  state.download = "idle";
  state.downloadId = null;
  render();
});

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
window.addEventListener("unload", stopWatching);

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
