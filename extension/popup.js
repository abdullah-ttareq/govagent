/**
 * منطق نافذة GovMind المنبثقة.
 *
 * **الإضافة لا تقرأ أي صفحة ولا تملك صلاحية لذلك**: لا Content Scripts ولا
 * `tabs` ولا `activeTab` ولا `scripting` في `manifest.json`. كل ما تفعله هو
 * الاتصال بسيرفر الجهة الذي يضبطه الموظف بنفسه.
 *
 * ثلاث حالات يتبدّل بينها الجسم — تحقّق، ودخول، ومحادثة — وارتفاع النافذة
 * ثابت في كلها (انظر `popup.css`).
 */

import {
  ApiError,
  fetchCurrentUser,
  listMessages,
  login as loginRequest,
  logout as logoutRequest,
  requestHostPermission,
  sendChatMessage,
} from "./lib/api.js";
import { actionLabel, describeFailure } from "./lib/errors.js";
import {
  clearConversationId,
  clearSession,
  getApiBaseUrl,
  getConversationId,
  getSession,
  setApiBaseUrl,
  setConversationId,
  setSession,
  updateSessionUser,
} from "./lib/storage.js";

const el = {
  newChat: document.getElementById("new-chat"),
  settingsToggle: document.getElementById("settings-toggle"),
  settings: document.getElementById("settings"),
  apiBaseUrl: document.getElementById("api-base-url"),
  saveSettings: document.getElementById("save-settings"),
  settingsStatus: document.getElementById("settings-status"),

  viewLoading: document.getElementById("view-loading"),
  viewLogin: document.getElementById("view-login"),
  viewChat: document.getElementById("view-chat"),

  loginNotice: document.getElementById("login-notice"),
  loginForm: document.getElementById("login-form"),
  email: document.getElementById("email"),
  password: document.getElementById("password"),
  loginSubmit: document.getElementById("login-submit"),
  loginError: document.getElementById("login-error"),
  loginErrorText: document.getElementById("login-error-text"),
  loginErrorAction: document.getElementById("login-error-action"),

  log: document.getElementById("log"),
  banner: document.getElementById("banner"),
  bannerText: document.getElementById("banner-text"),
  bannerAction: document.getElementById("banner-action"),
  composer: document.getElementById("composer"),
  message: document.getElementById("message"),
  send: document.getElementById("send"),

  themeRoot: document.getElementById("theme-root"),
  themeTrigger: document.getElementById("theme-trigger"),
  themeMenu: document.getElementById("theme-menu"),
  themeIcon: document.getElementById("theme-icon"),

  sessionBar: document.getElementById("session-bar"),
  who: document.getElementById("who"),
  logout: document.getElementById("logout"),
};

/** @type {{token: string, expiresAt: number, user: object|null}|null} */
let session = null;
/** @type {number|null} */
let conversationId = null;
/** يمنع إرسالين متزامنين على المحادثة نفسها. */
let sending = false;

/* =========================================================================
   تبديل الحالات
   ========================================================================= */

function showView(name) {
  el.viewLoading.hidden = name !== "loading";
  el.viewLogin.hidden = name !== "login";
  el.viewChat.hidden = name !== "chat";

  // «محادثة جديدة» وشريط الجلسة لا معنى لهما قبل الدخول.
  el.newChat.hidden = name !== "chat";
  el.sessionBar.hidden = name !== "chat";
}

/**
 * يعرض شاشة الدخول.
 *
 * `notice` سطر يشرح **لماذا** عاد الموظف إلى هنا: العودة بلا سبب ظاهر بعد
 * انتهاء الجلسة تبدو كأن الإضافة نسيت دخوله.
 */
function showLogin(notice) {
  hideLoginError();
  if (notice) {
    el.loginNotice.textContent = notice;
    el.loginNotice.hidden = false;
  } else {
    el.loginNotice.hidden = true;
    el.loginNotice.textContent = "";
  }
  el.password.value = "";
  showView("login");
  el.email.focus();
}

function showChat() {
  showView("chat");
  const user = session?.user;
  el.who.textContent = user
    ? [user.full_name, user.organization_name].filter(Boolean).join(" — ")
    : "";
  el.who.title = user?.email ?? "";
  el.message.focus();
}

/* =========================================================================
   عرض الأخطاء — رسالة وإجراء
   ========================================================================= */

/**
 * يعرض فشلًا في شريط الخطأ مع زر الإجراء المناسب.
 *
 * @param {"chat"|"login"} where أي شريط يُستخدم.
 * @param {{message: string, action: string}} failure
 * @param {(() => void)|null} retry ما يُعاد تنفيذه عند اختيار «أعد المحاولة».
 */
function showFailure(where, failure, retry = null) {
  const box = where === "login" ? el.loginError : el.banner;
  const text = where === "login" ? el.loginErrorText : el.bannerText;
  const button = where === "login" ? el.loginErrorAction : el.bannerAction;

  text.textContent = failure.message;
  const label = actionLabel(failure.action);

  if (label) {
    button.textContent = label;
    button.hidden = false;
    button.onclick = () => runFailureAction(failure.action, retry);
  } else {
    button.hidden = true;
    button.onclick = null;
  }

  box.hidden = false;
}

async function runFailureAction(action, retry) {
  switch (action) {
    case "settings":
      openSettings();
      break;
    case "permission": {
      // الطلب أولًا وبلا أي await قبله: إذن النطاق يحتاج نقرة المستخدم،
      // وأي انتظار قبله قد يُسقط أثر النقرة فيرفضه المتصفح بلا سؤال.
      const granted = await requestHostPermission(
        el.apiBaseUrl.value.trim() || "http://localhost:8000",
      );
      if (!granted) return;
      hideBanner();
      hideLoginError();
      if (retry) retry();
      else boot();
      break;
    }
    case "signin":
      await clearSession();
      session = null;
      conversationId = null;
      showLogin("انتهت جلستك. سجّل الدخول من جديد للمتابعة.");
      break;
    case "retry":
      hideBanner();
      hideLoginError();
      if (retry) retry();
      break;
    default:
      break;
  }
}

function hideBanner() {
  el.banner.hidden = true;
  el.bannerText.textContent = "";
  el.bannerAction.hidden = true;
  el.bannerAction.onclick = null;
}

function hideLoginError() {
  el.loginError.hidden = true;
  el.loginErrorText.textContent = "";
  el.loginErrorAction.hidden = true;
  el.loginErrorAction.onclick = null;
}

/**
 * يتعامل مع فشل داخل شاشة المحادثة.
 *
 * الجلسة الساقطة (401) تُخرج الموظف إلى شاشة الدخول، أما 403 — اشتراك
 * منتهٍ مثلًا — فتُبقيه داخلًا: الرسالة تشرح المنع، وإخراجه منها يوهم أن
 * المشكلة في بيانات دخوله.
 */
async function handleChatFailure(caught, fallback, retry = null) {
  const failure = describeFailure(caught, fallback);
  if (failure.sessionLost) {
    await clearSession();
    session = null;
    conversationId = null;
    showLogin(failure.message);
    return;
  }
  showFailure("chat", failure, retry);
}

/* =========================================================================
   سجل المحادثة
   ========================================================================= */

function clearLog() {
  el.log.replaceChildren();
}

function renderEmptyLog(text = "لا رسائل بعد. اكتب رسالتك في الأسفل للبدء.") {
  clearLog();
  const empty = document.createElement("p");
  empty.className = "log-empty";
  empty.textContent = text;
  el.log.append(empty);
}

/** يزيل رسالة «لا رسائل بعد» إن كانت معروضة. */
function dropEmptyState() {
  el.log.querySelector(".log-empty")?.remove();
}

/**
 * يضيف فقاعة إلى السجل ويعيدها.
 *
 * النص يُكتب بـ`textContent` دائمًا لا `innerHTML`: رد المزود نصٌّ قادم من
 * الشبكة، وحقنه كـHTML يجعل الرد قادرًا على تنفيذ سكربت داخل النافذة.
 */
function appendBubble(role, content) {
  dropEmptyState();
  const bubble = document.createElement("div");
  bubble.className = "bubble bubble-" + role;
  bubble.textContent = content;
  el.log.append(bubble);
  scrollToBottom();
  return bubble;
}

/** سطر المصادر أسفل رد الإيجنت، إن استُند إلى ملفات الجهة. */
function appendSources(bubble, sources) {
  if (!Array.isArray(sources) || sources.length === 0) return;
  const names = [...new Set(sources.map((source) => source.file_name))];
  const line = document.createElement("p");
  line.className = "bubble-sources";
  line.textContent = "المصادر: " + names.join("، ");
  bubble.append(line);
}

/** فقاعة انتظار مؤقتة تُستبدل بالرد أو تُزال عند الفشل. */
function appendTypingBubble() {
  dropEmptyState();
  const bubble = document.createElement("div");
  bubble.className = "bubble bubble-assistant";
  const dots = document.createElement("span");
  dots.className = "typing";
  dots.setAttribute("aria-label", "جارٍ انتظار رد الإيجنت");
  dots.append(
    document.createElement("span"),
    document.createElement("span"),
    document.createElement("span"),
  );
  bubble.append(dots);
  el.log.append(bubble);
  scrollToBottom();
  return bubble;
}

/** التمرير إلى آخر السجل — بعد كل إضافة وبعد استعادة المحادثة. */
function scrollToBottom() {
  el.log.scrollTop = el.log.scrollHeight;
}

/* =========================================================================
   استعادة آخر محادثة
   ========================================================================= */

/**
 * يعيد بناء السجل من **رسائل السيرفر** لا من نسخة محلية.
 *
 * المحفوظ في الجهاز هو معرّف المحادثة وحده؛ المحتوى يُقرأ من
 * `GET /api/conversations/{id}/messages` عند كل فتح، فتظهر في الإضافة
 * الرسائل التي أُرسلت من تطبيق الويب أيضًا، ولا يبقى نصّ محادثة على جهاز
 * الموظف.
 */
async function restoreConversation() {
  hideBanner();
  conversationId = await getConversationId();

  if (conversationId === null) {
    renderEmptyLog();
    return;
  }

  try {
    const page = await listMessages(session.token, conversationId);
    const messages = (page && page.messages) || [];
    if (messages.length === 0) {
      renderEmptyLog();
      return;
    }
    clearLog();
    for (const message of messages) {
      const bubble = document.createElement("div");
      const role = message.role === "user" ? "user" : "assistant";
      bubble.className = "bubble bubble-" + role;
      bubble.textContent = message.content;
      el.log.append(bubble);
    }
    scrollToBottom();
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) {
      // حُذفت المحادثة من تطبيق الويب — تُنسى هنا بلا رسالة خطأ.
      await clearConversationId();
      conversationId = null;
      renderEmptyLog("لم تعد المحادثة السابقة موجودة. ابدأ محادثة جديدة.");
      return;
    }
    renderEmptyLog("تعذّر عرض المحادثة السابقة.");
    await handleChatFailure(
      caught,
      "تعذّر تحميل المحادثة السابقة.",
      restoreConversation,
    );
  }
}

/* =========================================================================
   الإقلاع
   ========================================================================= */

async function boot() {
  showView("loading");
  el.apiBaseUrl.value = await getApiBaseUrl();

  session = await getSession();
  if (session === null) {
    showLogin();
    return;
  }

  // انتهاء معروف مسبقًا: لا داعي لرحلة شبكة تعيد 401 حتمًا.
  if (session.expiresAt && Date.now() >= session.expiresAt) {
    await clearSession();
    session = null;
    conversationId = null;
    showLogin("انتهت مدة جلستك. سجّل الدخول من جديد للمتابعة.");
    return;
  }

  try {
    // /api/auth/me يعمل ولو انتهى اشتراك الجهة، فنجاحه يعني أن الرمز صالح
    // والحساب مفعّل — لا أكثر. منع الاشتراك يظهر عند أول استخدام فعلي.
    const user = await fetchCurrentUser(session.token);
    session.user = user;
    await updateSessionUser(user);
  } catch (caught) {
    const failure = describeFailure(caught, "تعذّر التحقق من الجلسة.");

    // 403 من /me تعني حسابًا معطّلًا لا اشتراكًا منتهيًا: هذا المسار
    // وحده لا يفحص الاشتراك.
    if (
      failure.sessionLost ||
      (caught instanceof ApiError && caught.status === 403)
    ) {
      await clearSession();
      session = null;
      conversationId = null;
      showLogin(failure.message);
      return;
    }

    // السيرفر متوقف أو الإذن غير ممنوح: الجلسة سليمة، فلا يُخرَج الموظف
    // منها. يُعرض السبب وزر إعادة المحاولة داخل شاشة المحادثة.
    showChat();
    renderEmptyLog("تعذّر تحميل المحادثة السابقة.");
    showFailure("chat", failure, boot);
    return;
  }

  showChat();
  await restoreConversation();
}

/* =========================================================================
   تسجيل الدخول والخروج
   ========================================================================= */

/** الشكل نفسه الذي يفحصه `validate_email_shape` في الـBackend. */
function validateEmail(value) {
  const cleaned = value.trim();
  if (!cleaned) return "أدخل البريد الإلكتروني.";
  const at = cleaned.indexOf("@");
  const local = at === -1 ? cleaned : cleaned.slice(0, at);
  const domain = at === -1 ? "" : cleaned.slice(at + 1);
  if (at === -1 || !local || !domain.includes(".") || domain.startsWith(".")) {
    return "صيغة البريد الإلكتروني غير صحيحة. مثال: name@entity.gov.sa";
  }
  return null;
}

function setLoginBusy(busy) {
  el.loginSubmit.disabled = busy;
  el.loginSubmit.textContent = busy ? "جارٍ الدخول…" : "دخول";
}

async function handleLogin(event) {
  event.preventDefault();
  hideLoginError();

  const email = el.email.value.trim();
  const password = el.password.value;

  // تحقق أوّلي يوفّر رحلة شبكة لخطأ ظاهر، ولا يحلّ محلّ تحقق السيرفر.
  const emailProblem = validateEmail(email);
  if (emailProblem) {
    showFailure("login", { message: emailProblem, action: "none" });
    el.email.focus();
    return;
  }
  if (!password.trim()) {
    showFailure("login", { message: "أدخل كلمة المرور.", action: "none" });
    el.password.focus();
    return;
  }

  setLoginBusy(true);
  try {
    const token = await loginRequest(email, password);
    await setSession({
      accessToken: token.access_token,
      expiresIn: token.expires_in,
      user: token.user,
    });
    session = await getSession();
    el.password.value = "";
    el.loginNotice.hidden = true;
    showChat();
    await restoreConversation();
  } catch (caught) {
    // 401 هنا ليست جلسة منتهية بل بيانات دخول خاطئة، فتُعرض رسالة
    // الـBackend كما هي بدل «انتهت جلستك».
    const failure =
      caught instanceof ApiError && caught.status === 401
        ? { message: caught.message, action: "none" }
        : describeFailure(caught, "تعذّر تسجيل الدخول. حاول مرة أخرى.");
    showFailure("login", failure, () => el.loginForm.requestSubmit());
    el.password.focus();
  } finally {
    setLoginBusy(false);
  }
}

async function handleLogout() {
  el.logout.disabled = true;
  const token = session ? session.token : null;

  // الرمز موقّع وبلا حالة على السيرفر، فلا يُلغى بهذا النداء: النداء تأكيد
  // وسجل تدقيق. لذلك يُمسح المحلي مهما كانت نتيجته — بما فيها فشل الشبكة.
  if (token) {
    try {
      await logoutRequest(token);
    } catch {
      /* تجاهل عمدًا */
    }
  }

  await clearSession();
  session = null;
  conversationId = null;
  clearLog();
  hideBanner();
  el.logout.disabled = false;
  showLogin("تم تسجيل الخروج.");
}

/* =========================================================================
   الإرسال
   ========================================================================= */

function setSending(busy) {
  sending = busy;
  el.send.disabled = busy;
  el.message.disabled = busy;
  el.send.textContent = busy ? "جارٍ الإرسال…" : "إرسال";
}

async function handleSend(event) {
  if (event) event.preventDefault();
  if (sending || session === null) return;

  const message = el.message.value.trim();
  if (!message) {
    el.message.focus();
    return;
  }

  hideBanner();
  const userBubble = appendBubble("user", message);
  const typingBubble = appendTypingBubble();
  el.message.value = "";
  setSending(true);

  try {
    const body = await sendChatMessage(session.token, message, conversationId);

    typingBubble.remove();
    const replyBubble = appendBubble("assistant", (body && body.reply) || "");
    appendSources(replyBubble, body && body.sources);

    // المحادثة تُفتح على السيرفر عند أول رسالة، ومعرّفها يعود في الرد.
    if (body && body.conversation_id && body.conversation_id !== conversationId) {
      conversationId = body.conversation_id;
      await setConversationId(conversationId);
    }
  } catch (caught) {
    // لا شيء حُفظ على السيرفر عند الفشل: الحفظ يقع بعد نجاح المزود. لذلك
    // تُزال الفقاعة المتفائلة ويعود النص إلى الحقل ليعيد الموظف المحاولة
    // بلا إعادة كتابة.
    typingBubble.remove();
    userBubble.remove();
    if (el.log.childElementCount === 0) renderEmptyLog();
    el.message.value = message;
    await handleChatFailure(caught, "تعذّر إرسال الرسالة.", () => handleSend());
  } finally {
    setSending(false);
    if (!el.viewChat.hidden) el.message.focus();
  }
}

async function startNewConversation() {
  await clearConversationId();
  conversationId = null;
  hideBanner();
  renderEmptyLog("محادثة جديدة. اكتب رسالتك في الأسفل.");
  el.message.value = "";
  el.message.focus();
}

/* =========================================================================
   الإعدادات — رابط السيرفر
   ========================================================================= */

/** يزيل الشرطة المائلة الأخيرة ويتحقق أن الرابط صالح. */
function normalizeBaseUrl(value) {
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) {
    throw new Error("اكتب رابط السيرفر أولًا.");
  }
  let parsed;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error("الرابط غير صالح. مثال: http://localhost:8000");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("الرابط يجب أن يبدأ بـhttp أو https.");
  }
  return trimmed;
}

function openSettings() {
  el.settings.hidden = false;
  el.settingsToggle.setAttribute("aria-expanded", "true");
  el.apiBaseUrl.focus();
  el.apiBaseUrl.select();
}

function closeSettings() {
  el.settings.hidden = true;
  el.settingsToggle.setAttribute("aria-expanded", "false");
  el.settingsStatus.textContent = "";
}

function toggleSettings() {
  if (el.settings.hidden) openSettings();
  else closeSettings();
}

async function saveApiBaseUrl() {
  el.settingsStatus.textContent = "";

  let baseUrl;
  try {
    baseUrl = normalizeBaseUrl(el.apiBaseUrl.value);
  } catch (err) {
    el.settingsStatus.textContent = err.message;
    return;
  }

  const previous = await getApiBaseUrl();

  // `request` هو النداء غير المتزامن الأول بعد تحقّق متزامن: إذن النطاق
  // يحتاج نقرة المستخدم، وسبقه بانتظار طويل قد يُسقط أثرها. النطاق
  // الممنوح سلفًا يعود `true` فورًا بلا أي نافذة سؤال.
  const granted = await requestHostPermission(baseUrl);
  if (!granted) {
    el.settingsStatus.textContent =
      "لم يُمنح إذن الاتصال بهذا الرابط، فلم يُحفظ. اضغط «حفظ الرابط» ووافق على طلب المتصفح.";
    return;
  }

  await setApiBaseUrl(baseUrl);
  el.apiBaseUrl.value = baseUrl;

  if (baseUrl === previous) {
    el.settingsStatus.textContent = "تم حفظ الرابط.";
    return;
  }

  // سيرفر آخر يعني رمز دخول لا يعرفه: إبقاء الجلسة يعطي 401 غامضة عند أول
  // طلب. تُنهى الجلسة هنا صراحةً ويُشرح السبب.
  await clearSession();
  session = null;
  conversationId = null;
  clearLog();
  hideBanner();
  // تُغلق اللوحة هنا وحدها: سطر «تغيّر رابط السيرفر» أدلّ من «تم حفظ
  // الرابط»، وإبقاؤها مفتوحة يضيّق شاشة الدخول بلا فائدة.
  closeSettings();
  showLogin("تغيّر رابط السيرفر. سجّل الدخول على السيرفر الجديد.");
}

/* =========================================================================
   المظهر — فاتح وداكن وتلقائي

   الاختيار في `localStorage` لا في `chrome.storage.local`: القراءة متزامنة
   فيضبطه `theme-init.js` قبل أول رسم بلا وميض. ولا صلاحية جديدة لأيّهما.

   زرّ أيقونة يفتح قائمة، لا ثلاثة أزرار ظاهرة: الرأس ضيّق ويحمل «محادثة
   جديدة» و«الإعدادات» أصلًا. أيقونة الزرّ تعرض الوضع الفعّال.
   ========================================================================= */

const THEME_KEY = "govagent.theme";

//: مسارات الأيقونات — الشمس والقمر والشاشة.
const THEME_ICONS = {
  light:
    "M10 6a4 4 0 1 0 0 8 4 4 0 0 0 0-8m0 1.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5M10 1.5a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 1.5m0 14a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 15.5M18.5 10a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5a.75.75 0 0 1 .75.75m-14 0a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5a.75.75 0 0 1 .75.75m11.5-6a.75.75 0 0 1 0 1.06l-1.06 1.06a.75.75 0 1 1-1.06-1.06L14.94 4a.75.75 0 0 1 1.06 0M6.62 13.38a.75.75 0 0 1 0 1.06L5.56 15.5A.75.75 0 0 1 4.5 14.44l1.06-1.06a.75.75 0 0 1 1.06 0m9.38 2.12a.75.75 0 0 1-1.06 0l-1.06-1.06a.75.75 0 0 1 1.06-1.06l1.06 1.06a.75.75 0 0 1 0 1.06M6.62 6.62a.75.75 0 0 1-1.06 0L4.5 5.56A.75.75 0 0 1 5.56 4.5l1.06 1.06a.75.75 0 0 1 0 1.06",
  dark:
    "M16.3 12.6a6.6 6.6 0 0 1-8.9-8.9.75.75 0 0 0-.98-.98 8.1 8.1 0 1 0 10.86 10.86.75.75 0 0 0-.98-.98M10 16.6a6.6 6.6 0 0 1-4.6-11.3 8.1 8.1 0 0 0 9.9 9.9A6.57 6.57 0 0 1 10 16.6",
  system:
    "M3.5 4.25c0-.97.78-1.75 1.75-1.75h9.5c.97 0 1.75.78 1.75 1.75v7.5c0 .97-.78 1.75-1.75 1.75h-3.5v1.75h2a.75.75 0 0 1 0 1.5h-6.5a.75.75 0 0 1 0-1.5h2V13.5h-3.5a1.75 1.75 0 0 1-1.75-1.75zM5.25 4a.25.25 0 0 0-.25.25v7.5c0 .14.11.25.25.25h9.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25z",
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

/** يطبّق الوضع على المستند ويحدّث الأيقونة وحالة عناصر القائمة. */
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
    el.themeTrigger.setAttribute(
      "aria-label",
      `المظهر: ${THEME_LABELS[choice]}`,
    );
  }
  for (const item of document.querySelectorAll("[data-theme-choice]")) {
    item.setAttribute(
      "aria-checked",
      String(item.dataset.themeChoice === choice),
    );
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

// النقر خارج القائمة يغلقها، كأي طبقة عائمة.
document.addEventListener("mousedown", (event) => {
  if (!el.themeRoot?.contains(event.target)) closeThemeMenu();
});

// «تلقائي» يتابع تغيّر إعداد النظام والنافذة مفتوحة.
if (typeof window.matchMedia === "function") {
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (readThemeChoice() === "system") applyThemeChoice("system");
    });
}

// مزامنة الأيقونة والقائمة مع ما ضبطه سكربت الرأس.
applyThemeChoice(readThemeChoice());

/* =========================================================================
   الربط بالأحداث
   ========================================================================= */

el.settingsToggle.addEventListener("click", toggleSettings);
el.saveSettings.addEventListener("click", saveApiBaseUrl);
el.newChat.addEventListener("click", startNewConversation);
el.logout.addEventListener("click", handleLogout);
el.loginForm.addEventListener("submit", handleLogin);
el.composer.addEventListener("submit", handleSend);

// Enter يرسل، وShift+Enter يكتب سطرًا جديدًا. Ctrl+Enter يرسل كذلك، وهو
// ما اعتاده مستخدمو الـStarter.
el.message.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  if (event.shiftKey && !event.ctrlKey && !event.metaKey) return;
  event.preventDefault();
  handleSend();
});

// Escape يغلق الإعدادات ويعيد التركيز إلى زرّها، فلا يضيع مكان لوحة المفاتيح.
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !el.themeMenu?.hidden) {
    event.preventDefault();
    closeThemeMenu();
    el.themeTrigger?.focus();
    return;
  }
  if (event.key === "Escape" && !el.settings.hidden) {
    event.preventDefault();
    closeSettings();
    el.settingsToggle.focus();
  }
});

// حفظ الرابط بـEnter من داخل حقله.
el.apiBaseUrl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    saveApiBaseUrl();
  }
});

boot();
