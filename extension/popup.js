/**
 * منطق نافذة GovAgent المنبثقة.
 *
 * لا يقرأ الإضافة أي صفحة ولا تستخدم Content Scripts. كل ما تفعله هو إرسال
 * رسالة نصية إلى `POST {API_BASE_URL}/api/chat` وعرض الرد.
 */

const DEFAULT_API_BASE_URL = "http://localhost:8000";
const STORAGE_KEY = "apiBaseUrl";

const el = {
  settingsToggle: document.getElementById("settings-toggle"),
  settings: document.getElementById("settings"),
  apiBaseUrl: document.getElementById("api-base-url"),
  saveSettings: document.getElementById("save-settings"),
  settingsStatus: document.getElementById("settings-status"),
  message: document.getElementById("message"),
  send: document.getElementById("send"),
  loading: document.getElementById("loading"),
  error: document.getElementById("error"),
  replyBox: document.getElementById("reply-box"),
  reply: document.getElementById("reply"),
  provider: document.getElementById("provider"),
};

/** يعيد الرابط المحفوظ، أو الافتراضي إن لم يُحفظ شيء. */
async function getApiBaseUrl() {
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  return stored[STORAGE_KEY] || DEFAULT_API_BASE_URL;
}

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

function showError(text) {
  el.error.textContent = text;
  el.error.hidden = false;
}

function clearFeedback() {
  el.error.hidden = true;
  el.error.textContent = "";
  el.replyBox.hidden = true;
  el.reply.textContent = "";
  el.provider.textContent = "";
}

function setLoading(isLoading) {
  el.loading.hidden = !isLoading;
  el.send.disabled = isLoading;
  el.send.textContent = isLoading ? "جارٍ الإرسال…" : "إرسال";
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

  // الروابط خارج localhost تحتاج إذنًا صريحًا من المستخدم.
  const origin = new URL(baseUrl).origin + "/*";
  const alreadyGranted = await chrome.permissions.contains({ origins: [origin] });
  if (!alreadyGranted) {
    const granted = await chrome.permissions.request({ origins: [origin] });
    if (!granted) {
      el.settingsStatus.textContent =
        "لم يُمنح الإذن للاتصال بهذا الرابط، فلم يُحفظ.";
      return;
    }
  }

  await chrome.storage.local.set({ [STORAGE_KEY]: baseUrl });
  el.apiBaseUrl.value = baseUrl;
  el.settingsStatus.textContent = "تم حفظ الرابط.";
}

async function sendMessage() {
  clearFeedback();

  const message = el.message.value.trim();
  if (!message) {
    showError("اكتب رسالة قبل الإرسال.");
    return;
  }

  const baseUrl = await getApiBaseUrl();
  setLoading(true);

  let response;
  try {
    response = await fetch(`${baseUrl}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
  } catch {
    setLoading(false);
    showError(
      `تعذّر الاتصال بـ${baseUrl}. تأكد من تشغيل الـBackend ومن صحة الرابط في الإعدادات.`,
    );
    return;
  }

  setLoading(false);

  if (!response.ok) {
    if (response.status === 422) {
      showError("الرسالة غير مقبولة. تأكد أنها ليست فارغة.");
    } else if (response.status === 503) {
      showError("مزود المودل غير متاح حاليًا. راجع إعداد MODEL_PROVIDER.");
    } else {
      showError(`حدث خطأ أثناء إرسال الرسالة (رمز ${response.status}).`);
    }
    return;
  }

  let body;
  try {
    body = await response.json();
  } catch {
    showError("رد السيرفر غير مفهوم.");
    return;
  }

  el.reply.textContent = body.reply ?? "";
  el.provider.textContent = body.provider ? `المزود: ${body.provider}` : "";
  el.replyBox.hidden = false;
}

el.settingsToggle.addEventListener("click", () => {
  el.settings.hidden = !el.settings.hidden;
});
el.saveSettings.addEventListener("click", saveApiBaseUrl);
el.send.addEventListener("click", sendMessage);

// Ctrl+Enter داخل حقل الرسالة يرسل مباشرة.
el.message.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    sendMessage();
  }
});

getApiBaseUrl().then((baseUrl) => {
  el.apiBaseUrl.value = baseUrl;
});
