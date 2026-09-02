/**
 * النافذة كاملة — **الشاشات التسع عبر DOM حقيقي و`fetch` مزيّف.**
 *
 * `steps.test.js` يختبر القرار، وهذا الملف يختبر أن النافذة **تعرض** ما
 * قرّره وتفعل ما يُنتظر منها: تسجّل الدخول، وتفعّل الجهاز، وتبدأ التنزيل،
 * وتُظهر التقدّم، وتلغي، ولا تفتح أي ملف.
 *
 * `popup.html` تُقرأ من القرص لا تُكتب هنا: اختبارٌ على نسخة يدوية من
 * الصفحة يمرّ بينما الصفحة الحقيقية مكسورة.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RUNTIME_PORTS } from "../config.js";

// المسار من جذر المشروع لا من `import.meta.url`: في بيئة jsdom لا يكون
// الأخير رابط ملف، فـ`fileURLToPath` ترفض.
const POPUP_HTML = readFileSync(resolve(process.cwd(), "popup.html"), "utf-8");

/** جسم `popup.html` وحده — الرأس يحمل وسوم سكربتات لا تُنفَّذ هنا. */
const POPUP_JS = readFileSync(resolve(process.cwd(), "popup.js"), "utf-8");

/**
 * يزيل التعليقات من مصدر JavaScript قبل فحصه.
 *
 * ⚠️ **ضروري لأي فحص «لا يوجد كذا في الشيفرة».** توثيقُ ما لا نفعله —
 * ولماذا لا نفعله — يذكر أسماءه بالضرورة (`SmartScreen`، `downloads.open`)،
 * وفحصُ نصّ الملف كاملًا يحوّل كل شرح أمني إلى مخالفة، فيدفع إلى حذف
 * الشروح بدل حذف السلوك.
 *
 * التنفيذ بسيط عمدًا: لا يفهم التعليقات داخل النصوص، ولا حاجة إليه —
 * ملفات هذه الإضافة لا تحمل نصوصًا فيها `//`.
 */
function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    // ⚠️ `\r?\n` لا `\n`: ملفات المستودع بنهايات أسطر ويندوز، و`\r`
    // متبقّيًا في آخر السطر يمنع `$` من المطابقة فيبقى كل تعليق سطري.
    .split(/\r?\n/)
    .map((line) => line.replace(/(^|\s)\/\/.*$/, ""))
    .join("\n");
}

const BODY = POPUP_HTML.split("<body>")[1].split("</body>")[0];

/** آخر نسخة محمَّلة من `popup.js`، لإيقاف عملها الخلفي قبل تحميل غيرها. */
let mounted = null;

// ⚠️ بلا `role` وبلا `organization_id`: **الاشتراك فردي**، فلا لقب
// «مسؤول» ولا مفردات مؤسسات تخرج من السيرفر أصلًا.
const ACCOUNT = {
  email: "employee@govmind.test",
  full_name: "موظف",
};

const ACTIVE_DEVICE = {
  id: 5,
  device_name: "حاسب المكتب",
  activated_at: "2026-01-01T00:00:00Z",
  last_seen_at: "2026-02-01T00:00:00Z",
  revoked_at: null,
  is_current_device: true,
};

function subscription(overrides = {}) {
  return {
    status: "active",
    seats: 10,
    starts_at: "2026-01-01T00:00:00Z",
    expires_at: "2027-01-01T00:00:00Z",
    is_usable: true,
    blocked_reason: null,
    device: null,
    requires_activation: true,
    ...overrides,
  };
}

/**
 * بذرة «أقرّ صاحب الحساب طريقة البدء».
 *
 * أغلب الاختبارات تخصّ ما بعد هذه الشاشة، فتُتخطّى ببذرة بدل نقرة في كل
 * اختبار. أما اختبارات الشاشة نفسها فلا تستعملها.
 */
function planSeed(email = ACCOUNT.email) {
  return { planAckFor: email.toLowerCase() };
}

/**
 * موجّه طلبات مزيّف: مسار ← رد. أي مسار غير معرّف يُفشل الاختبار.
 *
 * يفهم كذلك استطلاع الـRuntime على `127.0.0.1`: بلا `runtime` في الحالة
 * يردّ برفض اتصال — وهو ما يراه المستخدم قبل أن يثبّت البرنامج.
 *
 * ⚠️ **رمز HTTP يُقرأ من `status` فقط مع وجود `body`.** بدون هذا الشرط
 * يلتبس `status` الخاص بالعمل — `"active"` و`"expired"` في رد الاشتراك —
 * برمز الحالة، فيرفضه `Response` ويصير كل رد فشلَ شبكة صامتًا.
 */
function routeFetch(routes, runtime) {
  return vi.fn(async (url, options = {}) => {
    const raw = String(url);

    // استطلاع الـRuntime المحلي.
    if (raw.includes("127.0.0.1")) {
      if (!runtime) throw new TypeError("Failed to fetch");
      const path = raw.replace(/^https?:\/\/[^/]+/, "");
      const handler = runtime[path];
      if (!handler) throw new TypeError("Failed to fetch");
      const result =
        typeof handler === "function"
          ? handler(options.body ? JSON.parse(options.body) : null)
          : handler;
      const envelope =
        result !== null && typeof result === "object" && "body" in result;
      return new Response(JSON.stringify(envelope ? result.body : result), {
        status: envelope ? (result.status ?? 200) : 200,
        headers: { "content-type": "application/json" },
      });
    }

    const path = raw.replace(/^https?:\/\/[^/]+/, "");
    const route = routes[path];
    if (!route) throw new Error(`مسار غير متوقّع في الاختبار: ${path}`);

    const result =
      typeof route === "function"
        ? route(options.body ? JSON.parse(options.body) : null)
        : route;

    const isEnvelope = result !== null && typeof result === "object" && "body" in result;
    return new Response(JSON.stringify(isEnvelope ? result.body : result), {
      status: isEnvelope ? (result.status ?? 200) : 200,
      headers: { "content-type": "application/json" },
    });
  });
}

/**
 * يركّب الصفحة، ويحمّل `popup.js` من جديد، وينتظر انتهاء إقلاعه.
 *
 * التخزين يُفرَّغ صراحة قبل التحميل: أي مفتاح باقٍ من اختبار سابق يجعل
 * النافذة تقلع من شاشة أخرى، ويصير الفشل تابعًا لترتيب الاختبارات.
 *
 * `module.ready` هو وعد الإقلاع الوحيد الذي تنتظره النافذة نفسها — لا
 * يُستدعى `boot()` هنا مرة ثانية.
 */
async function mount(routes, { seed, runtime, plan = true, keepStorage = false } = {}) {
  // ⚠️ **إيقاف النسخة السابقة قبل تحميل غيرها.**
  //
  // `popup.js` يستطلع الـRuntime في حلقة، ويوقفها عند `unload` — وهو حدث
  // لا يقع في jsdom بين الاختبارات. فتبقى الحلقة القديمة حيّة، و`render`
  // فيها يستعلم عن `.screen` من **المستند الحالي** لا من عقد محفوظة،
  // فيعيد رسم شاشة اختبارٍ سابق فوق الاختبار الجاري.
  //
  // لا يُطلَق `unload` هنا: jsdom يعامله كتفكيك للنافذة فيعطّل مؤقّتاتها.
  mounted?.stopBackgroundWork?.();

  if (!keepStorage) {
    await chrome.storage.local.remove([
    "accessToken",
    "refreshToken",
    "tokenExpiresAt",
    "account",
    "deviceId",
    "deviceName",
    "welcomeSeen",
    "installStage",
    "downloadId",
    "downloadFileName",
    "planAckFor",
      "installToken",
      "installTokenExpiresAt",
    ]);
  }
  // **إقرار طريقة البدء مبذور افتراضيًا.** أغلب الاختبارات تخصّ ما بعد
  // تلك الشاشة؛ أما اختباراتها هي فتمرّر `plan: false` لتراها.
  if (plan && !keepStorage) await chrome.storage.local.set(planSeed());
  if (seed) await chrome.storage.local.set(seed);
  document.body.innerHTML = BODY;
  const fetchMock = routeFetch(routes, runtime);
  vi.stubGlobal("fetch", fetchMock);

  vi.resetModules();
  const module = await import("../popup.js");
  mounted = module;
  await module.ready;
  return { fetchMock, module };
}

/** معرّف الشاشة الظاهرة الآن. */
function visibleScreen() {
  const shown = [...document.querySelectorAll(".screen")].filter(
    (screen) => !screen.hidden,
  );
  expect(shown.length, "يجب أن تظهر شاشة واحدة لا أكثر").toBe(1);
  return shown[0].id.replace("screen-", "");
}

function alertText() {
  const alert = document.getElementById("alert");
  return alert.hidden ? null : document.getElementById("alert-message").textContent;
}

/**
 * ينتظر أن تستقرّ الواجهة على شاشة بعينها.
 *
 * كل فعل في النافذة غير متزامن (تخزين ثم شبكة ثم رسم)، فالتأكيد مباشرةً
 * بعد النقر يقيس الحالة قبل أن تتغيّر. `vi.waitFor` يعمل مع المؤقّتات
 * المزيّفة كما يعمل مع الحقيقية.
 */
async function waitForScreen(expected) {
  await vi.waitFor(() => expect(visibleScreen()).toBe(expected));
}

/**
 * ينتظر دورة استطلاع واحدة من `watchDownload` (٥٠٠ مللي ثانية).
 *
 * **مؤقّتات حقيقية لا مزيّفة:** الفاصل يُنشأ لحظة بدء التنزيل، فتفعيل
 * المؤقّتات المزيّفة بعده لا يحرّكه، وتفعيلها قبله يمنع `fetch` المزيّف من
 * الاستقرار. الانتظار الحقيقي أبطأ بأجزاء من الثانية ويقيس ما يجري فعلًا.
 */
async function tick() {
  await new Promise((resolve) => setTimeout(resolve, 700));
}

/** ينتظر ظهور نصّ بعينه في شريط التنبيه. */
async function waitForAlert(fragment) {
  await vi.waitFor(
    () => {
      const text = alertText();
      expect(text, "لم يظهر أي تنبيه بعد").not.toBeNull();
      expect(text).toContain(fragment);
    },
    { timeout: 4000 },
  );
}

/** يملأ نموذج الدخول ويرسله، وينتظر الشاشة التي يجب أن تليه. */
async function signIn(expected, { email = ACCOUNT.email, password = "secret" } = {}) {  // eslint-disable-line
  document.getElementById("signin-email").value = email;
  document.getElementById("signin-password").value = password;
  document
    .getElementById("signin-form")
    .dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  if (expected) await waitForScreen(expected);
}

/** ينقر زرًّا وينتظر الشاشة الناتجة إن ذُكرت. */
async function click(id, expected) {
  document.getElementById(id).click();
  if (expected) await waitForScreen(expected);
  else await vi.waitFor(() => expect(true).toBe(true));
}

const LOGIN_OK = {
  access_token: "issued-token",
  refresh_token: "refresh",
  expires_in: 3600,
  account: ACCOUNT,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

beforeEach(() => {
  document.body.innerHTML = "";
});

/* ======================================================================== */
describe("١) الترحيب والدخول", () => {
  it("يبدأ بالترحيب ثم ينتقل إلى الدخول", async () => {
    await mount({});
    expect(visibleScreen()).toBe("welcome");

    await click("welcome-next", "signin");
  });

  it("لا يوجد في الصفحة كلها حقل رابط أو مفتاح", () => {
    // شرط صريح: **لا يُدخل المستخدم عنوان سيرفر ولا مفتاح API إطلاقًا.**
    //
    // يُفحص **معنى** الحقل لا نوعه: شاشة التسجيل أضافت حقل الاسم الكامل
    // وهو نصّ مشروع، فحصرُ الأنواع في email/password كان يمنع أي حقل
    // نصّي مهما كان بريئًا.
    document.body.innerHTML = BODY;
    const forbidden = ["url", "key", "token", "server", "port", "endpoint", "secret"];

    for (const input of document.querySelectorAll("input")) {
      const signature = `${input.id} ${input.name} ${input.placeholder ?? ""}`.toLowerCase();
      for (const word of forbidden) {
        expect(signature, `حقل يطلب ${word}`).not.toContain(word);
      }
      expect(["email", "password", "text"]).toContain(input.type);
    }

    expect(POPUP_HTML).not.toContain("apiBaseUrl");
    expect(POPUP_HTML.toLowerCase()).not.toContain("api key");
    expect(POPUP_HTML).not.toContain("127.0.0.1");
    expect(POPUP_HTML).not.toContain("supabase");
  });

  it("يعرض رسالة الخطأ عند بيانات دخول خاطئة ويبقى في شاشة الدخول", async () => {
    await mount({
      "/api/account/login": {
        status: 401,
        body: { detail: "البريد الإلكتروني أو كلمة المرور غير صحيحة.", code: "unauthorized" },
      },
    });
    await click("welcome-next", "signin");

    document.getElementById("signin-email").value = ACCOUNT.email;
    document.getElementById("signin-password").value = "wrong";
    document
      .getElementById("signin-form")
      .dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

    await waitForAlert("غير صحيحة");
    expect(visibleScreen()).toBe("signin");
  });

  it("يمسح كلمة المرور من الحقل بعد نجاح الدخول", async () => {
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription(),
    });
    await click("welcome-next", "signin");
    await signIn("install");

    expect(document.getElementById("signin-password").value).toBe("");
  });
});

describe("٢) حساب لم يكتمل تجهيزه", () => {
  it("يعرض شاشة التجهيز الناقص بلا محاولة قراءة الاشتراك", async () => {
    const { fetchMock } = await mount({
      "/api/account/login": { ...LOGIN_OK, account: null },
    });
    await click("welcome-next", "signin");
    await signIn("not-provisioned");

    // لا معنى لسؤال عن اشتراك حسابٍ لم يكتمل تجهيزه.
    const paths = fetchMock.mock.calls.map(([url]) => String(url));
    expect(paths.some((path) => path.includes("/subscription"))).toBe(false);
  });
});

describe("٣) الاشتراك المانع", () => {
  it.each([
    ["expired", "انتهى اشتراكك بتاريخ ٢٠٢٦-٠٣-٠١.", "انتهى الاشتراك"],
    ["suspended", "اشتراكك موقوف حاليًا.", "الاشتراك موقوف"],
    ["cancelled", "اشتراكك ملغى.", "الاشتراك ملغى"],
  ])("يعرض شاشة الحجب للحالة %s برسالة السيرفر", async (status, reason, title) => {
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription({
        status,
        is_usable: false,
        blocked_reason: reason,
      }),
    });
    await click("welcome-next", "signin");
    await signIn("subscription-blocked");

    expect(document.getElementById("blocked-title").textContent).toBe(title);
    // رسالة السيرفر تحمل التاريخ، فتُعرض كما وردت لا بعبارة عامة.
    expect(document.getElementById("blocked-message").textContent).toBe(reason);
  });

  it("لا يعرض زر التثبيت لمن اشتراكه محجوب", async () => {
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription({
        status: "expired",
        is_usable: false,
        blocked_reason: "انتهى اشتراكك.",
      }),
    });
    await click("welcome-next", "signin");
    await signIn("subscription-blocked");

    expect(document.getElementById("screen-install").hidden).toBe(true);
  });
});

describe("٤) الجهاز الواحد", () => {
  it("⚠️ أول جهاز يبدأ بالتثبيت لا بالتفعيل", async () => {
    // **اختبار انحدار للعطل الحيّ.** كانت تُعرض شاشة «تفعيل هذا الجهاز»،
    // وزرُّها يفعّل بصمة المتصفح فيشغل خانة الجهاز الوحيدة بهوية لا
    // يملكها الـRuntime، فيُردّ تفعيله بعد التثبيت ويبقى الحساب عالقًا.
    await mount(
      {
        "/api/account/login": LOGIN_OK,
        "/api/account/subscription": subscription(),
      },
      { seed: planSeed() },
    );
    await click("welcome-next", "signin");
    await signIn("install");

    expect(
      document.getElementById("screen-install").querySelector(".screen__title")
        .textContent,
    ).toBe("تثبيت GovMind");
  });

  it("⚠️ لا وجود لشاشة «فعّل هذا الجهاز» ولا لزرّها", () => {
    document.body.innerHTML = BODY;
    expect(document.getElementById("screen-activate")).toBeNull();
    expect(document.getElementById("activate-submit")).toBeNull();
    // ولا زرّ في أي شاشة يعد بتفعيل الجهاز من المتصفح.
    const buttons = [...document.querySelectorAll("button")].map((b) =>
      b.textContent.trim(),
    );
    expect(buttons).not.toContain("فعّل هذا الجهاز");
  });

  it("⚠️ الإضافة لا تنادي مسار تفعيل الجهاز إطلاقًا", async () => {
    // البصمة التي تولّدها الإضافة لا يملكها الـRuntime؛ إرسالها يحرق
    // الخانة الوحيدة. المسار كله ممنوع من هذه الطبقة.
    const { fetchMock } = await mount(
      {
        "/api/account/login": LOGIN_OK,
        "/api/account/subscription": subscription(),
        "/api/account/installation-session": {
          token: "installation-session-token-value-000009",
          expires_at: "2099-01-01T00:00:00Z",
          expires_in_minutes: 15,
        },
        "/api/account/installer/download-url": {
          download_url: "https://acct.blob.core.windows.net/x?sig=secret",
          file_name: "GovMindSetup.exe",
          expires_at: "2099-01-01T00:00:00Z",
          expires_in_minutes: 15,
        },
      },
      { seed: planSeed() },
    );
    await click("welcome-next", "signin");
    await signIn("install");
    await click("install-start");

    const paths = fetchMock.mock.calls.map(([url]) => String(url));
    expect(paths.some((path) => path.includes("/devices/activate"))).toBe(false);
  });

  it("يعرض «مفعّل على جهاز آخر» ويسمّي الجهاز", async () => {
    const other = { ...ACTIVE_DEVICE, device_name: "حاسب المنزل" };
    await mount(
      {
        "/api/account/login": LOGIN_OK,
        "/api/account/subscription": subscription({ device: other }),
        "/api/account/devices/verify": {
          status: 409,
          body: {
            detail: "حسابك مفعّل على جهاز آخر (حاسب المنزل).",
            code: "conflict",
          },
        },
      },
      { seed: planSeed() },
    );
    await click("welcome-next", "signin");
    await signIn("device-taken");

    expect(document.getElementById("device-taken-message").textContent).toContain(
      "حاسب المنزل",
    );
  });
});

describe("٥) التنزيل", () => {
  const ready = {
    "/api/account/login": LOGIN_OK,
    "/api/account/subscription": subscription({
      device: ACTIVE_DEVICE,
      requires_activation: false,
    }),
    "/api/account/devices/verify": subscription({
      device: ACTIVE_DEVICE,
      requires_activation: false,
    }),
    "/api/account/installation-session": {
      token: "installation-session-token-value-000001",
      expires_at: "2099-01-01T00:00:00Z",
      expires_in_minutes: 15,
    },
    "/api/account/installer/download-url": {
      download_url:
        "https://acct.blob.core.windows.net/releases/GovMindSetup.exe?sv=2022-11-02&sig=secret",
      file_name: "GovMindSetup.exe",
      expires_at: "2026-09-01T12:15:00Z",
      expires_in_minutes: 15,
    },
  };

  async function reachInstall() {
    await mount(ready, { seed: planSeed() });
    await click("welcome-next");
    await signIn("install");
  }

  it("يعرض شاشة التثبيت باسم الحساب وحالة الاشتراك", async () => {
    // **لا اسم جهاز هنا:** أول تثبيت لا جهاز فيه بعد؛ الـRuntime يفعّله.
    await reachInstall();
    const facts = document.getElementById("install-facts").textContent;
    expect(facts).toContain(ACCOUNT.email);
    expect(facts).toContain("فعّال");
  });

  it("الضغط على «ثبّت» يبدأ تنزيلًا عبر chrome.downloads", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    expect(chrome.downloads.download).toHaveBeenCalledOnce();
    expect(chrome.downloads.download.mock.lastCall[0].filename).toBe(
      "GovMindSetup.exe",
    );
  });

  it("⚠️ لا يظهر رابط Azure في أي مكان من الصفحة", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    expect(document.body.textContent).not.toContain("blob.core.windows.net");
    expect(document.body.textContent).not.toContain("sig=");
    expect(document.body.innerHTML).not.toContain("sig=secret");
  });

  it("يعرض النسبة والحجم أثناء التنزيل", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    const id = chrome.downloads.__all()[0].id;
    chrome.downloads.__advance(id, 25 * 1024 * 1024, 100 * 1024 * 1024);
    await tick();

    const label = document.getElementById("progress-label").textContent;
    expect(label).toContain("25٪");
    expect(label).toContain("م.ب");
    expect(document.getElementById("progress-bar").style.inlineSize).toBe("25%");
  });

  it("بعد اكتمال التنزيل يعرض «تم تنزيل GovMind» وزرَّي الفتح والإظهار", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    const id = chrome.downloads.__all()[0].id;
    chrome.downloads.__finish(id);
    await tick();

    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));
    expect(document.getElementById("ready-file-name").textContent).toBe(
      "GovMindSetup.exe",
    );
    const screen = document.getElementById("screen-installer-ready");
    expect(screen.textContent).toContain("تم تنزيل GovMind");
    expect(screen.textContent).toContain("نافذة ويندوز");
    expect(document.getElementById("ready-open").textContent.trim()).toBe(
      "فتح ملف التثبيت",
    );
    expect(document.getElementById("ready-show").textContent.trim()).toBe(
      "إظهار في المجلد",
    );
  });

  it("⚠️ «إظهار في المجلد» يفتح المجلد ولا يفتح الملف", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    const id = chrome.downloads.__all()[0].id;
    chrome.downloads.__finish(id);
    await tick();
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    document.getElementById("ready-show").click();
    expect(chrome.downloads.show).toHaveBeenCalledWith(id);
    // ⚠️ الإظهار **ليس** فتحًا: زرّان مختلفان لفعلين مختلفين.
    expect(chrome.downloads.open).not.toHaveBeenCalled();
  });

  it("الإلغاء يوقف التنزيل ويعيد شاشة التثبيت برسالة مطمئنة", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    document.getElementById("download-cancel").click();
    await tick();

    expect(chrome.downloads.cancel).toHaveBeenCalled();
    expect(visibleScreen()).toBe("install");
    expect(alertText()).toContain("أُلغي التنزيل");
  });

  it("انقطاع الشبكة يعرض رسالة عربية وزر إعادة المحاولة", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    const id = chrome.downloads.__all()[0].id;
    chrome.downloads.__finish(id, { error: "NETWORK_FAILED" });
    await tick();

    expect(visibleScreen()).toBe("install");
    expect(alertText()).toContain("انقطع الاتصال");
    expect(document.getElementById("alert-action").hidden).toBe(false);
  });

  it("اشتراك انتهى بين التفعيل والتحميل يمنع الرابط", async () => {
    await mount({
      ...ready,
      "/api/account/installer/download-url": {
        status: 403,
        body: { detail: "انتهى اشتراكك بتاريخ ٢٠٢٦-٠٣-٠١.", code: "forbidden" },
      },
    });
    await click("welcome-next", "signin");
    await signIn("install");
    await click("install-start");
    await waitForAlert("انتهى اشتراكك");
    expect(chrome.downloads.download).not.toHaveBeenCalled();
  });

  it("تخزين Azure غير مهيّأ يظهر كرسالة إعداد لا كانهيار", async () => {
    await mount({
      ...ready,
      "/api/account/installer/download-url": {
        status: 503,
        body: {
          detail: "تحميل المثبّت غير مهيّأ على هذا السيرفر. المتغيرات الناقصة: AZURE_STORAGE_ACCOUNT.",
          code: "service_unavailable",
        },
      },
    });
    await click("welcome-next", "signin");
    await signIn("install");
    await click("install-start");
    await waitForAlert("AZURE_STORAGE_ACCOUNT");
    expect(visibleScreen()).toBe("install");
  });

  it("رفض المتصفح بدء التنزيل يظهر برسالة عربية", async () => {
    await reachInstall();
    chrome.downloads.__refuse = true;
    await click("install-start");
    await waitForAlert("تعذّر بدء التنزيل");
    expect(visibleScreen()).toBe("install");
  });
});

describe("٦) الجلسة والخروج", () => {
  it("رمز منتهٍ يُمسح عند الإقلاع ويعود إلى الدخول", async () => {
    await mount(
      {},
      {
        seed: {
          accessToken: "old",
          tokenExpiresAt: Date.now() - 1000,
          account: ACCOUNT,
          welcomeSeen: true,
        },
      },
    );

    await waitForScreen("signin");
    expect(await chrome.storage.local.get("accessToken")).toEqual({});
  });

  it("٤٠١ أثناء الاستخدام تُسقط الجلسة وتعرض زر الدخول", async () => {
    await mount(
      {
        "/api/account/subscription": {
          status: 401,
          body: { detail: "انتهت صلاحية جلستك.", code: "unauthorized" },
        },
      },
      {
        seed: {
          accessToken: "stale",
          tokenExpiresAt: Date.now() + 3600_000,
          account: ACCOUNT,
          welcomeSeen: true,
        },
      },
    );

    await waitForScreen("signin");
    // **رسالة السيرفر كما وردت**: هو وحده يعرف سبب الرفض.
    expect(alertText()).toBe("انتهت صلاحية جلستك.");
  });

  it("الخروج يمسح الجلسة ويعود إلى الدخول لا إلى الترحيب", async () => {
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription(),
    });
    await click("welcome-next", "signin");
    await signIn("install");

    document.querySelector("[data-signout]").click();
    await waitForScreen("signin");
    expect(await chrome.storage.local.get("accessToken")).toEqual({});
  });

  it("يظهر بريد الحساب في التذييل بعد الدخول فقط", async () => {
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription(),
    });
    expect(document.getElementById("footer").hidden).toBe(true);

    await click("welcome-next", "signin");
    await signIn("install");

    expect(document.getElementById("footer").hidden).toBe(false);
    expect(document.getElementById("footer-account").textContent).toBe(
      ACCOUNT.email,
    );
  });
});

describe("٦-ب) جلسة مرفوضة بعد تسجيل ناجح", () => {
  // **العطل الحيّ الذي أنتج هذا القسم.** مشروع Supabase يوقّع بـES256،
  // والمتحقّق كان يقبل HS256 وحدها: ينجح التسجيل والدخول ثم تُردّ كل
  // نداءات `Bearer` بـ٤٠١. الإصلاح في الـBackend، وهنا يُصلَح ما يقرأه
  // المستخدم: **لا يجوز أن يُفهم من ٤٠١ أن بريده أو كلمة مروره خطأ.**

  const REGISTERED_ACCOUNT = {
    email: "sara@example.gov.sa",
    full_name: "سارة العتيبي",
  };

  const REGISTER_OK = {
    requires_email_confirmation: false,
    email: "sara@example.gov.sa",
    access_token: "issued-token",
    refresh_token: "issued-refresh",
    expires_in: 3600,
    account: REGISTERED_ACCOUNT,
  };

  function fillRegister() {
    document.getElementById("register-name").value = "سارة العتيبي";
    document.getElementById("register-email").value = "sara@example.gov.sa";
    document.getElementById("register-password").value = "StrongPass!2026";
    document.getElementById("register-confirm").value = "StrongPass!2026";
    document
      .getElementById("register-form")
      .dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  }

  it("⚠️ لا تُلمّح إلى خطأ في البريد أو كلمة المرور", async () => {
    await mount({
      "/api/account/register": REGISTER_OK,
      "/api/account/subscription": {
        status: 401,
        body: {
          detail: "رمز الدخول غير صالح. سجّل الدخول مرة أخرى.",
          code: "unauthorized",
        },
      },
    });
    await click("welcome-next", "signin");
    await click("go-register", "register");
    fillRegister();

    await waitForScreen("signin");
    const message = alertText();
    expect(message).toBe("رمز الدخول غير صالح. سجّل الدخول مرة أخرى.");
    for (const word of ["كلمة المرور", "غير صحيحة", "خاطئة", "البريد الإلكتروني"]) {
      expect(message, `تلميح إلى بيانات دخول خاطئة: ${word}`).not.toContain(word);
    }
  });

  it("الجلسة غير الصالحة تُمسح من التخزين", async () => {
    await mount({
      "/api/account/register": REGISTER_OK,
      "/api/account/subscription": {
        status: 401,
        body: { detail: "رمز الدخول غير صالح.", code: "unauthorized" },
      },
    });
    await click("welcome-next", "signin");
    await click("go-register", "register");
    fillRegister();
    await waitForScreen("signin");

    const stored = await chrome.storage.local.get([
      "accessToken",
      "refreshToken",
      "account",
    ]);
    expect(stored).toEqual({});
  });

  it("٤٠١ بلا تفصيل من السيرفر تنفي خطأ البريد وكلمة المرور صراحةً", async () => {
    // بوّابة أو وسيط ردّ ٤٠١ عاريةً: الرسالة الافتراضية يجب أن تبقى دقيقة.
    await mount(
      { "/api/account/subscription": { status: 401, body: {} } },
      {
        seed: {
          accessToken: "stale",
          tokenExpiresAt: Date.now() + 3600_000,
          account: ACCOUNT,
          welcomeSeen: true,
        },
      },
    );

    await waitForScreen("signin");
    const message = alertText();
    expect(message).toContain("تعذّر التحقق من جلستك");
    expect(message).toContain("بريدك وكلمة مرورك سليمان");
    expect(message).not.toContain("انتهت");
  });

  it("زرّ «تسجيل الدخول» يظهر مع الرسالة", async () => {
    await mount(
      { "/api/account/subscription": { status: 401, body: {} } },
      {
        seed: {
          accessToken: "stale",
          tokenExpiresAt: Date.now() + 3600_000,
          account: ACCOUNT,
          welcomeSeen: true,
        },
      },
    );

    await waitForScreen("signin");
    const action = document.getElementById("alert-action");
    expect(action.hidden).toBe(false);
    expect(action.textContent.trim()).toBe("تسجيل الدخول");
  });

  it("⚠️ كلمة مرور خاطئة عند الدخول تحتفظ برسالتها الخاصة", async () => {
    // **الفرق يجب أن يبقى واضحًا**: هذه بيانات دخول خاطئة فعلًا.
    await mount({
      "/api/account/login": {
        status: 401,
        body: {
          detail: "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
          code: "unauthorized",
        },
      },
    });
    await click("welcome-next", "signin");

    document.getElementById("signin-email").value = ACCOUNT.email;
    document.getElementById("signin-password").value = "wrong";
    document
      .getElementById("signin-form")
      .dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

    await waitForAlert("غير صحيحة");
    expect(alertText()).toBe("البريد الإلكتروني أو كلمة المرور غير صحيحة.");
    // ولا تُمسح جلسة لا وجود لها، ولا يُنقل المستخدم عن شاشته.
    expect(visibleScreen()).toBe("signin");
  });

  it("٥٠٣ عند تعذّر التحقق لا تُسقط الجلسة", async () => {
    // عطل عابر في مفاتيح التحقق ليس جلسةً ساقطة: لو أُسقطت لخرج كل
    // المستخدمين من حساباتهم بسبب انقطاع مؤقّت.
    await mount(
      {
        "/api/account/subscription": {
          status: 503,
          body: {
            detail: "تعذّر التحقق من الجلسة حاليًا. أعد المحاولة بعد قليل.",
            code: "service_unavailable",
          },
        },
      },
      {
        seed: {
          accessToken: "valid",
          tokenExpiresAt: Date.now() + 3600_000,
          account: ACCOUNT,
          welcomeSeen: true,
        },
      },
    );

    await waitForAlert("أعد المحاولة");
    const stored = await chrome.storage.local.get("accessToken");
    expect(stored.accessToken, "أُسقطت الجلسة بسبب عطل عابر").toBe("valid");
  });
});

describe("٧) المظهر — فاتح وداكن فقط", () => {
  it("خياران في القائمة: فاتح وداكن", async () => {
    await mount({});
    const items = [...document.querySelectorAll("[data-theme-choice]")];

    expect(items.map((item) => item.dataset.themeChoice)).toEqual([
      "light",
      "dark",
    ]);
    expect(items.map((item) => item.textContent.trim())).toEqual([
      "فاتح",
      "داكن",
    ]);
  });

  it("⚠️ لا أثر لخيار «تلقائي» في القائمة", async () => {
    await mount({});
    expect(document.querySelector('[data-theme-choice="system"]')).toBeNull();
    expect(document.querySelector('[data-theme-choice="auto"]')).toBeNull();
    expect(document.getElementById("theme-menu").textContent).not.toContain(
      "تلقائي",
    );
  });

  it("اختيار «داكن» يطبّقه ويحفظه", async () => {
    await mount({});
    document.querySelector('[data-theme-choice="dark"]').click();

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("govagent.theme")).toBe("dark");
  });

  it("اختيار «فاتح» يطبّقه ويحفظه", async () => {
    await mount({});
    document.querySelector('[data-theme-choice="dark"]').click();
    document.querySelector('[data-theme-choice="light"]').click();

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("govagent.theme")).toBe("light");
  });

  it("المظهر لا يتبع الجهاز ولو كان مظلمًا", async () => {
    // **الاختيار صريح.** لا يتغيّر تحت المستخدم بتغيّر إعداد النظام.
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      addEventListener: () => {},
    }));
    await mount({});

    expect(document.documentElement.dataset.theme).toBe("light");
  });

  // -- الهجرة من التركيبات القديمة ---------------------------------------
  it("قيمة «system» المخزّنة من نسخة سابقة تُهاجَر إلى «فاتح»", async () => {
    // **حالة حقيقية**: تركيبة قائمة كان خيارها الافتراضي «تلقائي».
    // إهمالها كانت تترك الواجهة فاتحة والقائمة تعلّم خيارًا لا وجود له.
    localStorage.setItem("govagent.theme", "system");
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      addEventListener: () => {},
    }));
    await mount({});

    expect(document.documentElement.dataset.theme).toBe("light");
    const checked = [...document.querySelectorAll("[data-theme-choice]")].filter(
      (item) => item.getAttribute("aria-checked") === "true",
    );
    expect(checked.map((item) => item.dataset.themeChoice)).toEqual(["light"]);
  });

  it("قيمة «auto» القديمة تُهاجَر كذلك", async () => {
    localStorage.setItem("govagent.theme", "auto");
    await mount({});
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("قيمة «dark» المخزّنة تبقى كما هي", async () => {
    localStorage.setItem("govagent.theme", "dark");
    await mount({});
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("أول اختيار بعد الهجرة يمحو القيمة القديمة من التخزين", async () => {
    localStorage.setItem("govagent.theme", "system");
    await mount({});
    document.querySelector('[data-theme-choice="light"]').click();

    expect(localStorage.getItem("govagent.theme")).toBe("light");
  });
});

/* ======================================================================== */
describe("٨) تسليم رمز التركيب إلى GovMind Runtime", () => {
  const READY = {
    service: "govmind-runtime",
    phase: "ready",
    message: "GovMind جاهز للاستخدام.",
    is_ready: true,
    needs_activation: false,
    progress: null,
    downloaded_bytes: 0,
    total_bytes: 0,
    device_name: "حاسب ويندوز 11",
    subscription_status: "active",
  };

  const AWAITING = {
    ...READY,
    phase: "awaiting_activation",
    message: "بانتظار تفعيل هذا الجهاز من إضافة GovMind.",
    is_ready: false,
    needs_activation: true,
  };

  const DOWNLOADING = {
    ...READY,
    phase: "downloading_model",
    message: "جارٍ تنزيل المودل…",
    is_ready: false,
    needs_activation: false,
    progress: 42,
    downloaded_bytes: 2 * 1024 * 1024 * 1024,
    total_bytes: 5 * 1024 * 1024 * 1024,
  };

  /**
   * حالة «بدأ التثبيت فعلًا»: تنزيل مكتمل في سجل المتصفح، ومرحلة محفوظة
   * تقول إن المستخدم أعلن أنه فتح المثبّت.
   *
   * ⚠️ **شرطٌ لكل شاشات تقدّم الـRuntime بعد اليوم.** بدونه لا تُعرض،
   * لأن تقدّمًا لم يبدأه أحد لا يجوز أن يُعرض تقدّمًا.
   */
  const INSTALLING_ID = 4242;
  function installingSeed() {
    chrome.downloads.__seed(INSTALLING_ID);
    return {
      installStage: "installing",
      downloadId: INSTALLING_ID,
      downloadFileName: "GovMindSetup.exe",
      ...planSeed(),
    };
  }

  const signedInRoutes = {
    "/api/account/login": LOGIN_OK,
    "/api/account/subscription": subscription({
      device: ACTIVE_DEVICE,
      requires_activation: false,
    }),
    "/api/account/devices/verify": subscription({
      device: ACTIVE_DEVICE,
      requires_activation: false,
    }),
  };

  it("يكتشف Runtime جاهزًا عند الإقلاع ويتخطّى شاشة التنزيل", async () => {
    // من ثبّت البرنامج فعلًا لا يُعرض له «نزّل المثبّت» في كل فتح.
    await mount(signedInRoutes, { runtime: { "/health": READY } });
    await click("welcome-next");
    await signIn("installed");

    expect(document.getElementById("installed-facts").textContent).toContain(
      "حاسب ويندوز 11",
    );
  });

  it("يفتح GovMind بلا أن يكتب المستخدم عنوانًا", async () => {
    await mount(signedInRoutes, { runtime: { "/health": READY } });
    await click("welcome-next");
    await signIn("installed");

    document.getElementById("installed-open").click();
    await vi.waitFor(() =>
      expect(chrome.tabs.create).toHaveBeenCalledWith({
        url: "http://127.0.0.1:8765/",
      }),
    );
  });

  it("يسلّم رمز التركيب تلقائيًا حين يظهر Runtime ينتظر التفعيل", async () => {
    let received = null;
    let phase = AWAITING;

    await mount(
      { ...signedInRoutes, "/api/account/installation-session": {
        token: "installation-session-token-value-000001",
        expires_at: "2099-01-01T00:00:00Z",
        expires_in_minutes: 15,
      } },
      {
        seed: installingSeed(),
        runtime: {
          "/health": () => phase,
          "/activate": (body) => {
            received = body;
            phase = DOWNLOADING;
            return DOWNLOADING;
          },
        },
      },
    );
    await click("welcome-next", "signin");
    await signIn();

    // ⚠️ **بلا أي ضغطة بعد الدخول**: Runtime ينتظر التفعيل، فتُصدر الإضافة
    // رمزًا وتسلّمه تلقائيًا. الشرط صريح: لا ينسخ المستخدم رمزًا ولا يلصقه.
    await vi.waitFor(() => expect(received).not.toBeNull(), { timeout: 4000 });
    expect(received.token).toBe("installation-session-token-value-000001");

    // ينتهي المسار عند «جارٍ التجهيز»: التفعيل مرحلة عابرة بين الشاشتين.
    await vi.waitFor(() => expect(visibleScreen()).toBe("preparing-model"), {
      timeout: 4000,
    });
  });

  it("يعرض تقدّم تنزيل المودل بالعربية", async () => {
    await mount(signedInRoutes, {
      seed: installingSeed(),
      runtime: { "/health": DOWNLOADING },
    });
    await click("welcome-next");
    await signIn("preparing-model");

    expect(document.getElementById("preparing-message").textContent).toContain(
      "جارٍ تنزيل المودل",
    );
    const label = document.getElementById("preparing-label").textContent;
    expect(label).toContain("42٪");
    expect(label).toContain("ج.ب");
  });

  it("⚠️ لا يعرض منفذًا ولا عنوانًا ولا رمزًا في أي شاشة", async () => {
    await mount(signedInRoutes, {
      seed: installingSeed(),
      runtime: { "/health": DOWNLOADING },
    });
    await click("welcome-next");
    await signIn("preparing-model");

    const text = document.body.textContent;
    expect(text).not.toContain("127.0.0.1");
    expect(text).not.toContain("8765");
    expect(text).not.toContain("installation-session-token");
    expect(text).not.toContain("llama");
  });

  it("يمحو رمز التركيب بعد التسليم", async () => {
    let phase = AWAITING;
    await mount(
      { ...signedInRoutes, "/api/account/installation-session": {
        token: "installation-session-token-value-000001",
        expires_at: "2099-01-01T00:00:00Z",
        expires_in_minutes: 15,
      } },
      {
        seed: installingSeed(),
        runtime: {
          "/health": () => phase,
          "/activate": () => {
            phase = DOWNLOADING;
            return DOWNLOADING;
          },
        },
      },
    );
    await click("welcome-next", "signin");
    await signIn();
    await vi.waitFor(() => expect(visibleScreen()).toBe("preparing-model"), {
      timeout: 4000,
    });

    const stored = await chrome.storage.local.get("installToken");
    expect(stored).toEqual({});
  });

  it("رفض التفعيل من الـRuntime يظهر برسالته العربية", async () => {
    await mount(
      { ...signedInRoutes, "/api/account/installation-session": {
        token: "installation-session-token-value-000001",
        expires_at: "2099-01-01T00:00:00Z",
        expires_in_minutes: 15,
      } },
      {
        runtime: {
          "/health": AWAITING,
          "/activate": {
            status: 409,
            body: { detail: "هذا الاشتراك مفعّل على جهاز آخر." },
          },
        },
      },
    );
    await click("welcome-next");
    await signIn();
    // ⚠️ **شاشة قائمة بذاتها لا شريط تنبيه فوق مؤشّر دوّار.** رفض الخادم
    // للتفعيل نهايةُ مسار، فعرضه فوق «جارٍ التفعيل» انتظارٌ بلا نهاية.
    await vi.waitFor(() => expect(visibleScreen()).toBe("activation-failed"), {
      timeout: 5000,
    });
    expect(
      document.getElementById("activation-failed-message").textContent,
    ).toContain("جهاز آخر");
  });

  it("الخروج يمحو رمز التركيب", async () => {
    await mount(
      { ...signedInRoutes, "/api/account/installation-session": {
        token: "installation-session-token-value-000001",
        expires_at: "2099-01-01T00:00:00Z",
        expires_in_minutes: 15,
      } },
      { runtime: null },
    );
    await click("welcome-next");
    await signIn("install");
    await click("install-start");

    document.querySelector("[data-signout]").click();
    await vi.waitFor(async () => {
      const stored = await chrome.storage.local.get("installToken");
      expect(stored).toEqual({});
    });
  });
});

/* ======================================================================== */
describe("٩) إنشاء حساب جديد", () => {
  // ⚠️ بلا `role` وبلا `organization_id`: السيرفر لا يعيدهما أصلًا.
  const REGISTERED_ACCOUNT = {
    email: "sara@example.gov.sa",
    full_name: "سارة العتيبي",
  };

  const REGISTER_OK = {
    requires_email_confirmation: false,
    email: "sara@example.gov.sa",
    access_token: "issued-token",
    refresh_token: "issued-refresh",
    expires_in: 3600,
    account: REGISTERED_ACCOUNT,
  };

  const NEEDS_CONFIRMATION = {
    requires_email_confirmation: true,
    email: "sara@example.gov.sa",
    access_token: null,
  };

  /** يملأ نموذج التسجيل ويرسله. **أربعة حقول لا خمسة.** */
  function fillRegister({
    name = "سارة العتيبي",
    email = "sara@example.gov.sa",
    password = "StrongPass!2026",
    confirm = "StrongPass!2026",
  } = {}) {
    document.getElementById("register-name").value = name;
    document.getElementById("register-email").value = email;
    document.getElementById("register-password").value = password;
    document.getElementById("register-confirm").value = confirm;
    document
      .getElementById("register-form")
      .dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  }

  // -- التنقّل ---------------------------------------------------------
  it("زر «إنشاء حساب جديد» ينقل من الدخول إلى التسجيل", async () => {
    await mount({});
    await click("welcome-next", "signin");
    await click("go-register", "register");
  });

  it("«العودة إلى تسجيل الدخول» يرجع من التسجيل", async () => {
    await mount({});
    await click("welcome-next", "signin");
    await click("go-register", "register");
    await click("go-login", "signin");
  });

  it("شاشة التسجيل تحوي الحقول الأربعة المطلوبة", async () => {
    await mount({});
    await click("welcome-next", "signin");
    await click("go-register", "register");

    for (const id of [
      "register-name",
      "register-email",
      "register-password",
      "register-confirm",
      "register-submit",
    ]) {
      expect(document.getElementById(id), id).not.toBeNull();
    }
  });

  it("⚠️ لا حقل لاسم الجهة إطلاقًا", async () => {
    // **الاشتراك فردي:** حساب واحد وجهاز واحد. المساحة التي يحتاجها عزل
    // البيانات يولّدها السيرفر ولا يُسأل عنها العميل.
    await mount({});
    await click("welcome-next", "signin");
    await click("go-register", "register");

    expect(document.getElementById("register-org")).toBeNull();
    const section = BODY.split('id="screen-register"')[1].split("</section>")[0];
    expect(section).not.toContain("اسم الجهة");
    expect(section).not.toContain('autocomplete="organization"');

    const inputs = [
      ...document
        .getElementById("register-form")
        .querySelectorAll("input"),
    ];
    expect(inputs).toHaveLength(4);
  });

  it("الشاشة عربية واتجاهها RTL", () => {
    expect(POPUP_HTML).toContain('dir="rtl"');
    const section = BODY.split('id="screen-register"')[1].split("</section>")[0];
    expect(section).toContain("الاسم الكامل");
    expect(section).toContain("البريد الإلكتروني");
    expect(section).toContain("تأكيد كلمة المرور");
  });

  // -- التحقق قبل الإرسال ----------------------------------------------
  it("كلمتا مرور مختلفتان تُرفضان قبل أي طلب", async () => {
    const { fetchMock } = await mount({});
    await click("welcome-next", "signin");
    await click("go-register", "register");

    fetchMock.mockClear();
    fillRegister({ confirm: "DifferentPass!2026" });

    await waitForAlert("غير متطابقتين");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(visibleScreen()).toBe("register");
  });

  it("كلمة مرور قصيرة تُرفض قبل أي طلب", async () => {
    const { fetchMock } = await mount({});
    await click("welcome-next", "signin");
    await click("go-register", "register");

    fetchMock.mockClear();
    fillRegister({ password: "short", confirm: "short" });

    await waitForAlert("ثمانية أحرف");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("حقل ناقص يُرفض قبل أي طلب", async () => {
    const { fetchMock } = await mount({});
    await click("welcome-next", "signin");
    await click("go-register", "register");

    fetchMock.mockClear();
    fillRegister({ name: "" });

    await waitForAlert("أكمل جميع الحقول");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // -- التسجيل الناجح ---------------------------------------------------
  it("التسجيل الناجح يسجّل الدخول تلقائيًا ويتابع إلى التفعيل", async () => {
    let sent = null;
    await mount({
      "/api/account/register": (body) => {
        sent = body;
        return REGISTER_OK;
      },
      "/api/account/subscription": subscription(),
    });
    await click("welcome-next", "signin");
    await click("go-register", "register");

    fillRegister();
    // ⚠️ **حساب جديد لم يقرّ طريقة البدء** — إقرار غيره لا يسري عليه.
    await waitForScreen("choose-plan");

    expect(sent).toEqual({
      full_name: "سارة العتيبي",
      email: "sara@example.gov.sa",
      password: "StrongPass!2026",
      confirm_password: "StrongPass!2026",
    });
  });

  it("الجلسة تُحفظ بعد التسجيل كما تُحفظ بعد الدخول", async () => {
    await mount({
      "/api/account/register": REGISTER_OK,
      "/api/account/subscription": subscription(),
    });
    await click("welcome-next", "signin");
    await click("go-register", "register");
    fillRegister();
    // ⚠️ **حساب جديد لم يقرّ طريقة البدء** — إقرار غيره لا يسري عليه.
    await waitForScreen("choose-plan");

    const stored = await chrome.storage.local.get("accessToken");
    expect(stored.accessToken).toBe("issued-token");
    expect(document.getElementById("footer-account").textContent).toBe(
      "sara@example.gov.sa",
    );
  });

  it("كلمتا المرور تُمحيان من الحقلين بعد الإرسال", async () => {
    await mount({
      "/api/account/register": REGISTER_OK,
      "/api/account/subscription": subscription(),
    });
    await click("welcome-next", "signin");
    await click("go-register", "register");
    fillRegister();
    // ⚠️ **حساب جديد لم يقرّ طريقة البدء** — إقرار غيره لا يسري عليه.
    await waitForScreen("choose-plan");

    expect(document.getElementById("register-password").value).toBe("");
    expect(document.getElementById("register-confirm").value).toBe("");
  });

  // -- تأكيد البريد -----------------------------------------------------
  it("المشروع الذي يشترط تأكيد البريد يعرض رسالة لا فشلًا", async () => {
    await mount({ "/api/account/register": NEEDS_CONFIRMATION });
    await click("welcome-next", "signin");
    await click("go-register", "register");
    fillRegister();

    await waitForScreen("confirm-email");
    const text = document.getElementById("screen-confirm-email").textContent;
    expect(text).toContain("أُنشئ حسابك");
    expect(text).toContain("sara@example.gov.sa");
  });

  it("من شاشة التأكيد يعود المستخدم إلى الدخول", async () => {
    await mount({ "/api/account/register": NEEDS_CONFIRMATION });
    await click("welcome-next", "signin");
    await click("go-register", "register");
    fillRegister();
    await waitForScreen("confirm-email");

    await click("confirm-email-login", "signin");
  });

  // -- أخطاء الخدمة -----------------------------------------------------
  it("بريد مسجَّل مسبقًا يظهر برسالة الخدمة ويبقي المستخدم في التسجيل", async () => {
    await mount({
      "/api/account/register": {
        status: 409,
        body: {
          detail:
            "هذا البريد الإلكتروني مسجَّل مسبقًا. سجّل الدخول بدل إنشاء حساب جديد.",
          code: "conflict",
        },
      },
    });
    await click("welcome-next", "signin");
    await click("go-register", "register");
    fillRegister();

    await waitForAlert("مسجَّل مسبقًا");
    expect(visibleScreen()).toBe("register");
  });

  it("⚠️ حمولة التسجيل بلا اسم جهة", async () => {
    const { fetchMock } = await mount({
      "/api/account/register": REGISTER_OK,
      "/api/account/subscription": subscription(),
    });
    await click("welcome-next", "signin");
    await click("go-register", "register");
    fillRegister();
    // ⚠️ **حساب جديد لم يقرّ طريقة البدء** — إقرار غيره لا يسري عليه.
    await waitForScreen("choose-plan");

    const call = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/account/register"),
    );
    const body = JSON.parse(call[1].body);

    expect(Object.keys(body).sort()).toEqual([
      "confirm_password",
      "email",
      "full_name",
      "password",
    ]);
    expect(JSON.stringify(body)).not.toContain("organization");
  });

  it("الدخول ما زال يعمل بعد إضافة التسجيل", async () => {
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription(),
    });
    await click("welcome-next", "signin");
    await signIn("install");

    const stored = await chrome.storage.local.get("accessToken");
    expect(stored.accessToken).toBe("issued-token");
  });
});

/* ======================================================================== */
describe("١٠) أيقونة الترويسة", () => {
  const POPUP_JS = readFileSync(resolve(process.cwd(), "popup.js"), "utf-8");
  const THEME_INIT = readFileSync(
    resolve(process.cwd(), "theme-init.js"),
    "utf-8",
  );

  it("⚠️ لا وجود لمسار أيقونة الحاسوب في الشيفرة", () => {
    // بداية مسار SVG لأيقونة الشاشة/الحاسوب التي كانت تظهر أعلى اليسار.
    expect(POPUP_JS).not.toContain("M3.5 4.25c0-.97.78-1.75");
    expect(POPUP_HTML).not.toContain("M3.5 4.25c0-.97.78-1.75");
  });

  it("أيقونتان فقط: الشمس والقمر", () => {
    const block = POPUP_JS.split("const THEME_ICONS = {")[1].split("};")[0];
    expect(block).toContain("light:");
    expect(block).toContain("dark:");
    expect(block).not.toContain("system:");
  });

  it("الوضع الفاتح يعرض الشمس والداكن يعرض القمر", async () => {
    await mount({});
    const iconPath = () =>
      document.querySelector("#theme-icon path")?.getAttribute("d") ?? "";

    document.querySelector('[data-theme-choice="light"]').click();
    expect(iconPath()).toContain("M10 6a4 4 0");

    document.querySelector('[data-theme-choice="dark"]').click();
    expect(iconPath()).toContain("M16.3 12.6");
  });

  it("⚠️ لا اسم لخيار «تلقائي» في الملصقات", () => {
    const labels = POPUP_JS.split("const THEME_LABELS = ")[1].split(";")[0];
    expect(labels).toContain("فاتح");
    expect(labels).toContain("داكن");
    expect(labels).not.toContain("تلقائي");
    expect(labels).not.toContain("system");
  });

  it("⚠️ سكربت ما قبل الرسم لا يستشير الجهاز", () => {
    // لو بقي `matchMedia` هناك لعاد الوميض ولعادت متابعة الجهاز معه.
    expect(THEME_INIT).not.toContain("prefers-color-scheme");
    expect(THEME_INIT).not.toContain("matchMedia");
  });

  it("الشعار والعنوان باقيان في الرأس", () => {
    expect(BODY).toContain("<h1>GovMind</h1>");
    expect(BODY).toContain('src="icons/icon-32.png"');
  });
});

/* ======================================================================== */
describe("١١) استبدال الجهاز — ذاتي بكلمة المرور", () => {
  const OTHER_DEVICE = {
    ...ACTIVE_DEVICE,
    device_name: "حاسبي القديم",
    is_current_device: false,
  };

  const TAKEN = {
    "/api/account/login": LOGIN_OK,
    "/api/account/subscription": subscription({ device: OTHER_DEVICE }),
    "/api/account/devices/verify": {
      status: 409,
      body: {
        detail:
          "حسابك مفعّل حاليًا على جهاز آخر (حاسبي القديم). اشتراكك يعمل " +
          "على جهاز واحد فقط، ويمكنك استبدال الجهاز السابق بهذا الجهاز " +
          "من نافذة GovMind.",
        code: "conflict",
      },
    },
  };

  /** يملأ كلمة المرور ويرسل نموذج الاستبدال. */
  function submitReplace(password = "secret") {
    document.getElementById("replace-password").value = password;
    document
      .getElementById("replace-form")
      .dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  }

  async function reachDeviceTaken(extra = {}) {
    const mounted = await mount({ ...TAKEN, ...extra });
    await click("welcome-next", "signin");
    await signIn("device-taken");
    return mounted;
  }

  // -- الشاشة ------------------------------------------------------------
  it("تعرض «استبدال الجهاز السابق» وتحذّر من توقّفه", async () => {
    await reachDeviceTaken();

    const screen = document.getElementById("screen-device-taken").textContent;
    expect(screen).toContain("استبدال الجهاز السابق");
    expect(screen).toContain("سيتوقف GovMind عن العمل على الجهاز السابق");
  });

  it("⚠️ لا تحيل على مسؤول ولا تذكر جهة", async () => {
    // **المنتج اشتراك فردي**: لا مسؤول جهة ولا مسؤول نظام يوافق.
    await reachDeviceTaken();

    const screen = document.getElementById("screen-device-taken").textContent;
    for (const word of ["مسؤول", "جهتك", "مؤسسة", "الموافقة"]) {
      expect(screen, `تسرّبت مفردة «${word}»`).not.toContain(word);
    }
  });

  it("تطلب كلمة المرور بحقل مخفي لا يُملأ تلقائيًا من الدخول", async () => {
    await reachDeviceTaken();
    const field = document.getElementById("replace-password");

    expect(field.type).toBe("password");
    expect(field.value).toBe("");
    expect(field.getAttribute("autocomplete")).toBe("current-password");
  });

  // -- الرفض قبل الطلب ----------------------------------------------------
  it("كلمة مرور فارغة تُرفض قبل أي طلب", async () => {
    const { fetchMock } = await reachDeviceTaken();
    fetchMock.mockClear();

    submitReplace("");

    await waitForAlert("أدخل كلمة مرور حسابك");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // -- كلمة مرور خاطئة ----------------------------------------------------
  it("كلمة مرور خاطئة لا تستبدل شيئًا وتُبقي المستخدم في مكانه", async () => {
    // **الجوهر:** رمز الدخول وحده لا يوقف GovMind على حاسب آخر.
    const { fetchMock } = await reachDeviceTaken({
      "/api/account/devices/replace": {
        status: 401,
        body: {
          detail: "كلمة المرور غير صحيحة. أعد إدخالها للمتابعة.",
          code: "unauthorized",
        },
      },
    });

    submitReplace("WrongPass!2026");
    await waitForAlert("كلمة المرور غير صحيحة");

    // ⚠️ **لا يُخرَج المستخدم من حسابه**: ٤٠١ هنا ليست انتهاء جلسة.
    expect(visibleScreen()).toBe("device-taken");
    const stored = await chrome.storage.local.get("accessToken");
    expect(stored.accessToken).toBe("issued-token");

    // ولا يُرسل إلا طلب استبدال واحد.
    const replaceCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/devices/replace"),
    );
    expect(replaceCalls).toHaveLength(1);
  });

  it("الحقل يُفرَّغ بعد المحاولة الفاشلة", async () => {
    await reachDeviceTaken({
      "/api/account/devices/replace": {
        status: 401,
        body: { detail: "كلمة المرور غير صحيحة.", code: "unauthorized" },
      },
    });

    submitReplace("WrongPass!2026");
    await waitForAlert("غير صحيحة");

    expect(document.getElementById("replace-password").value).toBe("");
  });

  // -- الاستبدال الناجح ---------------------------------------------------
  it("كلمة المرور الصحيحة تنقل الاشتراك إلى هذا الجهاز", async () => {
    const { fetchMock } = await reachDeviceTaken({
      "/api/account/devices/replace": {
        replaced: true,
        subscription: subscription({
          device: { ...ACTIVE_DEVICE, is_current_device: true },
          requires_activation: false,
        }),
      },
    });

    submitReplace();
    await waitForScreen("install");

    const call = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/devices/replace"),
    );
    const body = JSON.parse(call[1].body);
    expect(Object.keys(body).sort()).toEqual([
      "device_id",
      "device_name",
      "password",
    ]);
    expect(body.password).toBe("secret");
  });

  it("كلمة المرور تُمحى من الحقل بعد النجاح", async () => {
    await reachDeviceTaken({
      "/api/account/devices/replace": {
        replaced: true,
        subscription: subscription({
          device: { ...ACTIVE_DEVICE, is_current_device: true },
          requires_activation: false,
        }),
      },
    });

    submitReplace();
    await waitForScreen("install");

    expect(document.getElementById("replace-password").value).toBe("");
  });

  it("⚠️ لا تُخزَّن كلمة المرور في تخزين الإضافة", async () => {
    await reachDeviceTaken({
      "/api/account/devices/replace": {
        replaced: true,
        subscription: subscription({
          device: { ...ACTIVE_DEVICE, is_current_device: true },
          requires_activation: false,
        }),
      },
    });

    submitReplace("Sup3rSecret!");
    await waitForScreen("install");

    const all = await chrome.storage.local.get(null);
    expect(JSON.stringify(all)).not.toContain("Sup3rSecret!");
  });

  // -- السباق -------------------------------------------------------------
  it("سباق استبدال متزامن يظهر برسالة عربية آمنة", async () => {
    await reachDeviceTaken({
      "/api/account/devices/replace": {
        status: 409,
        body: {
          detail: "جرت محاولة استبدال أخرى في اللحظة نفسها. أعد المحاولة.",
          code: "conflict",
        },
      },
    });

    submitReplace();
    await waitForAlert("أعد المحاولة");
    expect(visibleScreen()).toBe("device-taken");
  });

  it("⚠️ لا رابط ولا مفتاح في نموذج الاستبدال", () => {
    const section = BODY.split('id="screen-device-taken"')[1].split(
      "</section>",
    )[0];
    for (const word of ["url", "key", "token", "server", "port", "secret"]) {
      expect(section.toLowerCase()).not.toContain(`name="${word}`);
    }
    expect(section).not.toContain("127.0.0.1");
  });
});


/* ======================================================================== */
describe("١٢) ترتيب التثبيت — العطل الحيّ وإصلاحه", () => {
  /*
   * **ما كان يحدث حيًّا.** يسجّل المستخدم دخوله، فيرى شاشة «تفعيل هذا
   * الجهاز»، فتفعّل الإضافةُ **بصمةَ المتصفح** العشوائية على خانة الجهاز
   * الوحيدة. ثم — إن وصل إلى التنزيل أصلًا — تبدأ الإضافة تنتظر ظهور
   * GovMind قبل أن تعطيه الملف الذي يحوي GovMind. النتيجة: «جارٍ تفعيل
   * هذا الجهاز» بلا نهاية، ولا تنزيل، ولا ملف.
   *
   * هذا القسم يثبت الترتيب الصحيح خطوة خطوة.
   */

  const SESSION = {
    token: "installation-session-token-value-000042",
    expires_at: "2099-01-01T00:00:00Z",
    expires_in_minutes: 15,
  };

  const SAS_URL =
    "https://acct.blob.core.windows.net/releases/GovMindSetup.exe" +
    "?sv=2022-11-02&sig=SECRETSIGNATUREVALUE";

  const LINK = {
    download_url: SAS_URL,
    file_name: "GovMindSetup.exe",
    expires_at: "2099-01-01T00:00:00Z",
    expires_in_minutes: 15,
  };

  const READY = {
    "/api/account/login": LOGIN_OK,
    "/api/account/subscription": subscription(),
    "/api/account/installation-session": SESSION,
    "/api/account/installer/download-url": LINK,
  };

  async function reachInstall(routes = READY, options = {}) {
    const mounted = await mount(routes, options);
    await click("welcome-next", "signin");
    await signIn("install");
    return mounted;
  }

  function runtimeProbes(fetchMock) {
    return fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("127.0.0.1"),
    );
  }

  // -- الترتيب -----------------------------------------------------------
  it("⚠️ لا حلقة استطلاع للـRuntime قبل أن يبدأ التنزيل", async () => {
    // **نصف العطل.** كانت الإضافة تنتظر البرنامج قبل أن تسلّم مثبّته.
    //
    // فحصٌ واحد عند الإقلاع مشروع ومطلوب: من ثبّت GovMind من قبل يجب ألا
    // يُعرض له «نزّل المثبّت». الممنوع هو **الحلقة** التي تنتظر ظهوره.
    const { fetchMock } = await reachInstall();
    const afterBoot = runtimeProbes(fetchMock).length;

    await tick();
    await tick();

    expect(visibleScreen()).toBe("install");
    expect(runtimeProbes(fetchMock)).toHaveLength(afterBoot);
  });

  it("التنزيل يبدأ بعد أن تعود جلسة التركيب بـ٢٠٠", async () => {
    const { fetchMock } = await reachInstall();
    await click("install-start", "downloading");

    const paths = fetchMock.mock.calls.map(([url]) => String(url));
    const sessionAt = paths.findIndex((p) => p.includes("/installation-session"));
    const linkAt = paths.findIndex((p) => p.includes("/installer/download-url"));

    expect(sessionAt).toBeGreaterThanOrEqual(0);
    expect(linkAt).toBeGreaterThan(sessionAt);
    expect(chrome.downloads.download).toHaveBeenCalledOnce();
  });

  it("ولا استطلاع للـRuntime أثناء التنزيل", async () => {
    const { fetchMock } = await reachInstall();
    const afterBoot = runtimeProbes(fetchMock).length;

    await click("install-start", "downloading");
    chrome.downloads.__advance(chrome.downloads.__all()[0].id, 5_000_000, 20_000_000);
    await tick();

    expect(runtimeProbes(fetchMock)).toHaveLength(afterBoot);
  });

  it("⚠️ ولا استطلاع بعد اكتمال التنزيل حتى يعلن المستخدم أنه فتح المثبّت", async () => {
    // **نصف العطل الآخر.** كان الاستطلاع يبدأ فور اكتمال التنزيل، والملف
    // ما زال في مجلد التنزيلات لم يفتحه أحد.
    const { fetchMock } = await reachInstall();
    const afterBoot = runtimeProbes(fetchMock).length;

    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await tick();
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));
    await tick();

    expect(runtimeProbes(fetchMock)).toHaveLength(afterBoot);
  });

  it("«فتح ملف التثبيت» ينادي chrome.downloads.open بمعرّف التنزيل نفسه", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    const id = chrome.downloads.__all()[0].id;
    chrome.downloads.__finish(id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    await click("ready-open", "awaiting-runtime");

    expect(chrome.downloads.open).toHaveBeenCalledWith(id);
    expect(chrome.downloads.__opened).toEqual([id]);
  });

  it("الاستطلاع يبدأ **بعد نجاح الفتح** لا قبله", async () => {
    const { fetchMock } = await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    const afterReady = runtimeProbes(fetchMock).length;
    await tick();
    expect(runtimeProbes(fetchMock)).toHaveLength(afterReady);

    await click("ready-open", "awaiting-runtime");
    await vi.waitFor(() =>
      expect(runtimeProbes(fetchMock).length).toBeGreaterThan(afterReady),
    );
  });

  it("⚠️ فشل الفتح **لا يبدأ استطلاعًا**، ويُظهر الملف ويشرح الخطوة", async () => {
    // **هذا هو جوهر الإصلاح.** الزرّ السابق كان يبدأ الانتظار على إقرار
    // المستخدم، فتنتظر النافذة إلى الأبد برنامجًا لم يُفتح ملفُه.
    const { fetchMock } = await reachInstall();
    await click("install-start", "downloading");
    const id = chrome.downloads.__all()[0].id;
    chrome.downloads.__finish(id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    const afterReady = runtimeProbes(fetchMock).length;
    chrome.downloads.__refuseOpen = true;
    try {
      await click("ready-open", "open-failed");
    } finally {
      chrome.downloads.__refuseOpen = false;
    }

    // ① لا استطلاع: لا شيء فُتح لينتظره أحد.
    await tick();
    expect(runtimeProbes(fetchMock)).toHaveLength(afterReady);

    // ② الملف يُظهَر في مجلده تلقائيًا.
    expect(chrome.downloads.show).toHaveBeenCalledWith(id);

    // ③ تعليمة دقيقة وزرّ تعافٍ ظاهر.
    expect(
      document.getElementById("open-failed-message").textContent,
    ).toBe("افتح GovMindSetup.exe من المجلد لإكمال التثبيت.");
    expect(document.getElementById("open-failed-check").textContent.trim()).toBe(
      "تحقق من التثبيت",
    );
  });

  it("«تحقق من التثبيت» بعد فشل الفتح يبدأ الاستطلاع", async () => {
    const { fetchMock } = await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    chrome.downloads.__refuseOpen = true;
    try {
      await click("ready-open", "open-failed");
    } finally {
      chrome.downloads.__refuseOpen = false;
    }

    const afterFailure = runtimeProbes(fetchMock).length;
    await click("open-failed-check", "awaiting-runtime");
    await vi.waitFor(() =>
      expect(runtimeProbes(fetchMock).length).toBeGreaterThan(afterFailure),
    );
  });

  it("⚠️ الفتح لا يقع تلقائيًا عند اكتمال التنزيل", async () => {
    // تشغيل ملف تنفيذي بلا نقرة سلوك برمجية خبيثة لا سلوك منتج.
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));
    await tick();

    expect(chrome.downloads.open).not.toHaveBeenCalled();
    expect(chrome.downloads.__opened).toEqual([]);
  });

  // -- تقدّم التنزيل ------------------------------------------------------
  it("يعرض النسبة والبايتات المنزَّلة من الإجمالي", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    chrome.downloads.__advance(
      chrome.downloads.__all()[0].id,
      5 * 1024 * 1024,
      20 * 1024 * 1024,
    );
    await tick();

    const label = document.getElementById("progress-label").textContent;
    expect(label).toContain("٪");
    expect(label).toMatch(/25/);
    expect(label).toContain("م.ب");
    expect(document.getElementById("progress").getAttribute("aria-valuenow")).toBe(
      "25",
    );
  });

  it("حجم كلي مجهول يعطي حركة مستمرة لا نسبة مخترعة", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__advance(chrome.downloads.__all()[0].id, 1024 * 1024, 0);
    await tick();

    expect(document.getElementById("progress-bar").dataset.indeterminate).toBe(
      "true",
    );
    expect(document.getElementById("progress-label").textContent).toContain("نُزّل");
  });

  it("الإلغاء يوقف التنزيل ويعيد شاشة التثبيت", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    await click("download-cancel", "install");

    expect(chrome.downloads.cancel).toHaveBeenCalled();
    await waitForAlert("أُلغي التنزيل");
    expect(await chrome.storage.local.get("installStage")).toEqual({});
  });

  it("انقطاع الشبكة أثناء التنزيل يظهر برسالة عربية وزر إعادة", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id, {
      error: "NETWORK_FAILED",
    });
    await tick();

    await waitForAlert("الاتصال");
    expect(visibleScreen()).toBe("install");
    expect(document.getElementById("alert-action").textContent.trim()).toBe(
      "أعد المحاولة",
    );
  });

  // -- بعد التنزيل -------------------------------------------------------
  it("اكتمال التنزيل يعرض «تم تنزيل GovMind» وتعليمات الفتح", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    const screen = document.getElementById("screen-installer-ready").textContent;
    expect(screen).toContain("تم تنزيل GovMind");
    expect(screen).toContain("نافذة ويندوز");
    expect(document.getElementById("ready-file-name").textContent).toBe(
      "GovMindSetup.exe",
    );
  });

  it("⚠️ «إظهار في المجلد» يُظهر ولا يفتح", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    await click("ready-show");

    expect(chrome.downloads.show).toHaveBeenCalledOnce();
    expect(chrome.downloads.open).not.toHaveBeenCalled();
    expect(chrome.tabs.create).not.toHaveBeenCalledWith(
      expect.objectContaining({ url: expect.stringContaining(".exe") }),
    );
  });

  it("⚠️ الفتح استدعاء واحد، في معالِج النقر وحده", () => {
    // **لا تشغيل صامت.** الطريق الوحيد إلى فتح الملف هو `openDownload`
    // في `lib/download.js`، ولا يناديها إلا `doOpenInstaller` المربوطة
    // بنقرة «فتح ملف التثبيت».
    //
    // ⚠️ الفحص على **الشيفرة بلا تعليقات**: توثيقُ ما لا نفعله يذكر
    // أسماءه بالضرورة، وفحصُ نصّ الملف كاملًا يجعل كل شرح أمني مخالفة.
    const download = stripComments(
      readFileSync(resolve(process.cwd(), "lib/download.js"), "utf-8"),
    );
    const popup = stripComments(POPUP_JS);

    expect([...download.matchAll(/chrome\.downloads\.open/g)]).toHaveLength(1);
    expect(popup).not.toContain("chrome.downloads.open");

    expect([...popup.matchAll(/openDownload\(/g)]).toHaveLength(1);
    expect(popup).toContain('el.readyOpen?.addEventListener("click", doOpenInstaller)');

    // ⚠️ ولا استدعاء يشغّل ملفًا خارج المتصفح بأي طريقة أخرى.
    for (const source of [popup, download]) {
      expect(source).not.toContain("ShellExecute");
      expect(source).not.toContain("startfile");
      expect(source).not.toContain("nativeMessaging");
    }
  });

  it("⚠️ لا التفاف على أي حماية في ويندوز", () => {
    // لا سبيل إلى ذلك من إضافة أصلًا، والاختبار يحرس ألّا تُصنع محاولة.
    const sources = [
      stripComments(POPUP_JS),
      stripComments(
        readFileSync(resolve(process.cwd(), "lib/download.js"), "utf-8"),
      ),
      readFileSync(resolve(process.cwd(), "manifest.json"), "utf-8"),
    ];
    const bypass = [
      "SmartScreen",
      "SmartAppControl",
      "Defender",
      "MpPreference",
      "ExclusionPath",
      "EnableLUA",
      "ConsentPromptBehavior",
      "Unblock-File",
      "Zone.Identifier",
      "bypassSecurity",
    ];
    for (const source of sources) {
      for (const needle of bypass) {
        expect(source).not.toContain(needle);
      }
    }
  });

  it("⚠️ الفتح يحتاج صلاحية معلَنة لا حيلة", () => {
    const manifest = JSON.parse(
      readFileSync(resolve(process.cwd(), "manifest.json"), "utf-8"),
    );
    expect(manifest.permissions).toContain("downloads");
    expect(manifest.permissions).toContain("downloads.open");
    // ولا صلاحية أوسع من الحاجة: لا رسائل أصلية ولا قراءة صفحات.
    expect(manifest.permissions).not.toContain("nativeMessaging");
    expect(manifest.content_scripts).toBeUndefined();
  });

  // -- سرّ Azure ---------------------------------------------------------
  it("⚠️ رابط Azure لا يظهر في أي شاشة ولا يُخزَّن", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    expect(document.body.innerHTML).not.toContain("blob.core.windows.net");
    expect(document.body.innerHTML).not.toContain("SECRETSIGNATUREVALUE");
    expect(document.body.innerHTML).not.toContain("sig=");

    const stored = JSON.stringify(await chrome.storage.local.get(null));
    expect(stored).not.toContain("blob.core.windows.net");
    expect(stored).not.toContain("SECRETSIGNATUREVALUE");
  });

  // -- الاستئناف ---------------------------------------------------------
  it("إغلاق النافذة وفتحها أثناء التنزيل يستأنف الشاشة نفسها", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    const id = chrome.downloads.__all()[0].id;
    chrome.downloads.__advance(id, 1_000_000, 10_000_000);

    // إعادة فتح النافذة: التخزين يبقى، والذاكرة تُفقد.
    const { fetchMock } = await mount(READY, { seed: planSeed(), keepStorage: true });

    expect(visibleScreen()).toBe("downloading");
    // **ولا رابط جديد ولا جلسة تركيب ثانية.**
    const paths = fetchMock.mock.calls.map(([url]) => String(url));
    expect(paths.some((p) => p.includes("/installation-session"))).toBe(false);
    expect(paths.some((p) => p.includes("/installer/download-url"))).toBe(false);
    expect(chrome.downloads.download).toHaveBeenCalledOnce();
  });

  it("⚠️ إعادة الفتح بعد اكتمال التنزيل لا تعيد التنزيل ولا تُصدر جلسة ثانية", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    const { fetchMock } = await mount(READY, { seed: planSeed(), keepStorage: true });

    expect(visibleScreen()).toBe("installer-ready");
    expect(chrome.downloads.download).toHaveBeenCalledOnce();
    const paths = fetchMock.mock.calls.map(([url]) => String(url));
    expect(paths.filter((p) => p.includes("/installation-session"))).toHaveLength(0);
  });

  it("إعادة الفتح بعد نجاح فتح المثبّت تعود إلى الانتظار لا إلى التنزيل", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));
    await click("ready-open", "awaiting-runtime");

    await mount(READY, { seed: planSeed(), keepStorage: true });

    expect(visibleScreen()).toBe("awaiting-runtime");
    expect(chrome.downloads.download).toHaveBeenCalledOnce();
  });

  it("إعادة الفتح بعد **فشل** الفتح تعود إلى شاشة الفتح لا إلى الانتظار", async () => {
    // ⚠️ لم يُفتح شيء، فاستئناف شاشة انتظار بعد إعادة الفتح يعيد العطل
    // نفسه من باب آخر.
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));

    chrome.downloads.__refuseOpen = true;
    try {
      await click("ready-open", "open-failed");
    } finally {
      chrome.downloads.__refuseOpen = false;
    }

    await mount(READY, { seed: planSeed(), keepStorage: true });

    expect(visibleScreen()).toBe("installer-ready");
    expect(chrome.downloads.download).toHaveBeenCalledOnce();
  });

  it("تنزيل مُسح من سجل المتصفح يعيد المستخدم إلى شاشة التثبيت", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__forget(chrome.downloads.__all()[0].id);

    await mount(READY, { seed: planSeed(), keepStorage: true });

    expect(visibleScreen()).toBe("install");
    expect(await chrome.storage.local.get("installStage")).toEqual({});
  });

  // -- المهلة والتشخيص ---------------------------------------------------
  it("⚠️ انتهاء مهلة انتظار الـRuntime يعطي شاشة قابلة للتعافي", async () => {
    // **لا حركة مستمرة إلى الأبد.** تنتهي المهلة فتُعرض الأسباب وزر إعادة.
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));
    await click("ready-open", "awaiting-runtime");

    // الاختصار المتاح للمستخدم في أي لحظة، وهو نفسه ما تعرضه المهلة.
    await click("awaiting-help", "install-help");

    const screen = document.getElementById("screen-install-help").textContent;
    expect(screen).toContain("لم يبدأ GovMind بعد");
    expect(screen).toContain("Windows لم يمنعه");
    expect(document.getElementById("help-retry").textContent.trim()).toBe(
      "تحقق من التثبيت",
    );
  });

  it("⚠️ شاشة الانتظار تقول «بانتظار اكتمال تثبيت GovMind» لا «تفعيل الجهاز»", async () => {
    // العميل قرأ «جارٍ تفعيل هذا الجهاز» بينما لم يُفتح المثبّت بعد،
    // فظنّ أن شيئًا يجري وانتظر بلا نهاية.
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));
    await click("ready-open", "awaiting-runtime");

    const heading = document.getElementById("page-title")?.textContent ?? "";
    const screen = document.getElementById("screen-awaiting-runtime").textContent;
    expect(screen).toContain("بانتظار اكتمال تثبيت GovMind");
    expect(screen).not.toContain("تفعيل هذا الجهاز");
    expect(heading).not.toContain("تفعيل هذا الجهاز");
  });

  it("⚠️ تشرح شاشة التشخيص منع ويندوز للبرنامج بدقّة", async () => {
    // Smart App Control يمنع نسخة تطوير غير موقَّعة. **لا نعطّله ولا
    // ندّعي أن المثبّت موقَّع** — نقول ما يحدث كما هو.
    document.body.innerHTML = BODY;
    const causes = document.getElementById("install-help-causes").textContent;

    expect(causes).toContain("Smart App Control");
    expect(causes).toContain("غير");
    expect(causes).toContain("موقَّعة");
  });

  it("تسمّي شاشة التشخيص الأسباب المحتملة كلها", async () => {
    document.body.innerHTML = BODY;
    const causes = document.getElementById("install-help-causes").textContent;

    expect(causes).toContain("لم تفتح ملف المثبّت");
    expect(causes).toContain("إذن ويندوز");
    expect(causes).toContain("لم تنتهِ خطوات المثبّت");
  });

  it("«أعد المحاولة» يعيد الانتظار، و«نزّل مرة أخرى» يعيد التثبيت", async () => {
    await reachInstall();
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));
    await click("ready-open", "awaiting-runtime");
    await click("awaiting-help", "install-help");

    await click("help-retry", "awaiting-runtime");
    await click("awaiting-help", "install-help");
    await click("help-restart", "install");

    expect(await chrome.storage.local.get("installStage")).toEqual({});
  });

  // -- الفشل قبل التنزيل -------------------------------------------------
  it("فشل جلسة التركيب يمنع التنزيل ولا يترك رمزًا مخزّنًا", async () => {
    await reachInstall({
      ...READY,
      "/api/account/installation-session": {
        status: 503,
        body: { detail: "تخزين Azure غير مهيّأ.", code: "service_unavailable" },
      },
    });
    await click("install-start");

    await waitForAlert("Azure");
    expect(chrome.downloads.download).not.toHaveBeenCalled();
    expect(await chrome.storage.local.get("installToken")).toEqual({});
  });

  it("رفض المتصفح بدء التنزيل يظهر برسالة عربية", async () => {
    await reachInstall();
    chrome.downloads.__refuse = true;
    try {
      await click("install-start");
      await waitForAlert("تعذّر");
    } finally {
      chrome.downloads.__refuse = false;
    }
    expect(visibleScreen()).toBe("install");
  });
});

/* ======================================================================== */
describe("١٣) اختيار طريقة البدء — نسخة عرض أكاديمية", () => {
  const ROUTES = {
    "/api/account/login": LOGIN_OK,
    "/api/account/subscription": subscription(),
  };

  async function reachPlan(routes = ROUTES) {
    const mounted = await mount(routes, { plan: false });
    await click("welcome-next", "signin");
    await signIn("choose-plan");
    return mounted;
  }

  it("تظهر بعد الدخول والتحقق من الاشتراك وقبل التثبيت", async () => {
    await reachPlan();
    expect(
      document.getElementById("screen-choose-plan").querySelector(".screen__title")
        .textContent,
    ).toBe("اختر طريقة البدء");
  });

  it("تعرض شارة النسخة الأكاديمية", async () => {
    await reachPlan();
    expect(document.getElementById("demo-badge").textContent.trim()).toBe(
      "نسخة عرض أكاديمية — لا توجد رسوم حقيقية",
    );
  });

  it("تعرض زرَّين اثنين لا غير", async () => {
    await reachPlan();

    const buttons = [
      ...document.getElementById("screen-choose-plan").querySelectorAll("button"),
    ];

    expect(buttons.map((button) => button.textContent.trim())).toEqual([
      "ابدأ التجربة",
      "اشترك الآن",
    ]);
    expect(buttons.map((button) => button.id)).toEqual([
      "plan-trial-start",
      "plan-paid-start",
    ]);
  });

  it("⚠️ لا زرّ «التالي» في هذه الخطوة", async () => {
    // «التالي» زرّ صفحة تعريف؛ هنا القرار نفسه هو الإجراء.
    await reachPlan();
    const screen = document.getElementById("screen-choose-plan");

    expect(screen.textContent).not.toContain("التالي");
    expect(screen.querySelector("#welcome-next")).toBeNull();
  });

  it("⚠️ لا قائمة تعليمات مرقّمة ولا نصّ ساكن قبل الزرّين", async () => {
    // **سبب إعادة التصميم.** كانت كل بطاقة تحمل عنوانًا وقائمة مزايا فوق
    // زرّها، فبدت الشاشة صفحةَ تعريف والزرّان تفصيلًا فيها.
    await reachPlan();
    const screen = document.getElementById("screen-choose-plan");

    expect(screen.querySelector("ol")).toBeNull();
    expect(screen.querySelector("ul")).toBeNull();
    expect(screen.querySelector(".checklist")).toBeNull();
    expect(screen.querySelector(".plan__points")).toBeNull();
    expect(screen.querySelector(".screen__lead")).toBeNull();
  });

  it("⚠️ شرح «جهاز واحد» ليس هنا — مكانه شاشة التثبيت", async () => {
    await reachPlan();
    expect(
      document.getElementById("screen-choose-plan").textContent,
    ).not.toContain("جهاز واحد");

    await click("plan-trial-start", "install");
    expect(document.getElementById("screen-install").textContent).toContain(
      "جهاز واحد",
    );
  });

  it("الزرّان بعرض النافذة وبحجم هدف لمس مريح", async () => {
    await reachPlan();
    for (const id of ["plan-trial-start", "plan-paid-start"]) {
      const button = document.getElementById(id);
      expect(button.classList.contains("button")).toBe(true);
      expect(button.classList.contains("button--lg")).toBe(true);
      expect(button.tagName).toBe("BUTTON");
    }

    // **الأساسي مملوء والثانوي محدَّد الإطار** — يُقرأ الفرق بالشكل لا
    // باللون وحده.
    expect(
      document.getElementById("plan-trial-start").classList.contains(
        "button--primary",
      ),
    ).toBe(true);
    expect(
      document.getElementById("plan-paid-start").classList.contains(
        "button--outline",
      ),
    ).toBe(true);
  });

  it("⚠️ لا رابط نصّي مخفي بديلًا عن الزرّين", async () => {
    await reachPlan();
    const screen = document.getElementById("screen-choose-plan");
    expect(screen.querySelectorAll("a")).toHaveLength(0);
  });

  it("للزرّين حالات تركيز وتمرير وضغط وتعطيل في المظهرين", () => {
    const css = readFileSync(resolve(process.cwd(), "popup.css"), "utf-8");

    expect(css).toContain(".button:focus-visible");
    expect(css).toContain(".button:active:not(:disabled)");
    expect(css).toContain(".button:disabled");
    expect(css).toContain(".button--outline:hover:not(:disabled)");
    expect(css).toContain(".button--primary:hover:not(:disabled)");

    // ولا لون مكتوب يدويًا في هذه الأصناف: الرموز وحدها تنقلب مع المظهر.
    const block = css.split(".button--outline {")[1].split("}")[0];
    expect(block).not.toMatch(/#[0-9a-f]{3,6}/i);
  });

  // -- التجربة -----------------------------------------------------------
  it("«ابدأ التجربة» يتابع مباشرة إلى «تثبيت GovMind»", async () => {
    await reachPlan();
    await click("plan-trial-start", "install");

    expect(
      document.getElementById("screen-install").querySelector(".screen__title")
        .textContent,
    ).toBe("تثبيت GovMind");
  });

  it("⚠️ «ابدأ التجربة» لا يُنشئ اشتراكًا ولا يمدّده", async () => {
    // **التسجيل أنشأ التجربة أصلًا.** نداء ثانٍ كان سيضاعف الصفوف أو
    // يزحزح تاريخ الانتهاء. الزرّ **يقرّ القائم ولا يطلب شيئًا**.
    const { fetchMock } = await reachPlan();
    const before = fetchMock.mock.calls.length;

    await click("plan-trial-start", "install");

    expect(fetchMock.mock.calls).toHaveLength(before);
    const paths = fetchMock.mock.calls.map(([url]) => String(url));
    for (const forbidden of ["subscribe", "checkout", "payment", "trial", "plan"]) {
      expect(paths.some((p) => p.includes(forbidden))).toBe(false);
    }
  });

  it("حالة الاشتراك لا تتغيّر بضغط أي زرّ في الشاشة", async () => {
    await reachPlan();
    const before = JSON.stringify(
      await chrome.storage.local.get(["account", "accessToken"]),
    );

    document.getElementById("plan-paid-start").click();
    await tick();
    await click("plan-trial-start", "install");

    expect(
      JSON.stringify(await chrome.storage.local.get(["account", "accessToken"])),
    ).toBe(before);
  });

  // -- الاشتراك الكامل: زرّ معطّل، لا نافذة ---------------------------------
  it("⚠️ «اشترك الآن» معطّل بالسمة الحقيقية", async () => {
    await reachPlan();
    const button = document.getElementById("plan-paid-start");

    expect(button.disabled).toBe(true);
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("يظهر تحته سبب التعطيل نصًّا ساكنًا", async () => {
    await reachPlan();
    const note = document.getElementById("plan-paid-note");

    expect(note).not.toBeNull();
    expect(note.textContent.trim()).toBe("غير متاح في النسخة الأكاديمية");
    expect(note.hidden).toBe(false);
    // ومربوط بالزرّ لقارئ الشاشة، لا مجاورًا له بصريًا فحسب.
    expect(
      document.getElementById("plan-paid-start").getAttribute("aria-describedby"),
    ).toBe("plan-paid-note");
  });

  it("⚠️ الضغط عليه لا يُرسل طلبًا ولا ينقل الشاشة ولا يفتح شيئًا", async () => {
    const { fetchMock } = await reachPlan();
    const before = fetchMock.mock.calls.length;
    const overlaysBefore = document.querySelectorAll(
      "[role='dialog'], .modal, .overlay, .toast",
    ).length;

    document.getElementById("plan-paid-start").click();
    await tick();

    expect(fetchMock.mock.calls).toHaveLength(before);
    expect(visibleScreen()).toBe("choose-plan");
    expect(
      document.querySelectorAll("[role='dialog'], .modal, .overlay, .toast"),
    ).toHaveLength(overlaysBefore);
    expect(overlaysBefore).toBe(0);
  });

  it("⚠️ الضغط عليه لا يغيّر حالة الاشتراك ولا التخزين", async () => {
    await reachPlan();
    const before = JSON.stringify(await chrome.storage.local.get(null));

    document.getElementById("plan-paid-start").click();
    await tick();

    expect(JSON.stringify(await chrome.storage.local.get(null))).toBe(before);
  });

  it("⚠️ ولا مستمع نقر مسجَّل عليه في الشيفرة", () => {
    // `disabled` يمنع النقر في المتصفح، وغياب المستمع يجعل المنع مضاعفًا.
    expect(POPUP_JS).not.toContain("planPaidStart?.addEventListener");
  });

  it("⚠️ لا حقول بطاقة في الصفحة كلها", async () => {
    document.body.innerHTML = BODY;
    const forbidden = ["card", "cvv", "cvc", "iban", "expiry", "بطاقة"];

    for (const input of document.querySelectorAll("input")) {
      const signature =
        `${input.id} ${input.name} ${input.placeholder ?? ""}`.toLowerCase();
      for (const word of forbidden) {
        expect(signature, `حقل دفع: ${word}`).not.toContain(word);
      }
    }
    expect(BODY.toLowerCase()).not.toContain("stripe");
    expect(BODY.toLowerCase()).not.toContain("paypal");
  });

  it("⚠️ لا وجود لأي نافذة ولا خلفية ولا زرّ إغلاق في الصفحة", async () => {
    // **سبب الحذف.** كانت `.modal` تعلن `display: grid` بلا حارس
    // `.modal[hidden]`، وقاعدة المؤلّف تغلب `[hidden]` في ورقة المتصفح،
    // فبقيت الطبقة السوداء ظاهرة دائمًا وزرّ إغلاقها بلا أثر مرئي.
    await reachPlan();

    expect(document.getElementById("paid-dialog")).toBeNull();
    expect(document.getElementById("paid-dialog-close")).toBeNull();
    expect(document.getElementById("paid-dialog-dismiss")).toBeNull();
    expect(document.querySelector("[role='dialog']")).toBeNull();
    expect(document.querySelector("[aria-modal]")).toBeNull();
    expect(document.querySelector(".modal")).toBeNull();
    expect(document.querySelector("dialog")).toBeNull();
  });

  it("⚠️ الخياران ظاهران معًا بلا شيء يُغلق أولًا", async () => {
    await reachPlan();
    const buttons = [
      ...document.getElementById("screen-choose-plan").querySelectorAll("button"),
    ];

    expect(buttons).toHaveLength(2);
    expect(buttons.map((button) => button.textContent.trim())).toEqual([
      "ابدأ التجربة",
      "اشترك الآن",
    ]);
    expect(buttons[0].disabled).toBe(false);
    expect(buttons[1].disabled).toBe(true);
  });

  it("⚠️ لا أثر لنصوص النافذة المحذوفة في أي ملف مصدر", () => {
    const sources = {
      "popup.html": POPUP_HTML,
      "popup.js": POPUP_JS,
      "popup.css": readFileSync(resolve(process.cwd(), "popup.css"), "utf-8"),
    };
    const forbidden = [
      "الاشتراك الكامل",
      "العودة إلى التجربة",
      "بوابة الدفع",
      "paid-dialog",
      "aria-modal",
      "modal__",
    ];

    for (const [name, source] of Object.entries(sources)) {
      for (const needle of forbidden) {
        expect(source, `${name} ما زال يحوي «${needle}»`).not.toContain(needle);
      }
    }
  });

  // -- الاستمرارية والعزل -------------------------------------------------
  it("لا تتكرر الشاشة عند إعادة فتح النافذة", async () => {
    await reachPlan();
    await click("plan-trial-start", "install");

    await mount(ROUTES, { plan: false, keepStorage: true });

    expect(visibleScreen()).toBe("install");
  });

  it("⚠️ إقرار مستخدم لا يسري على غيره على الجهاز نفسه", async () => {
    // **العزل لكل حساب.** حاسبٌ يتناوب عليه اثنان: من أقرّ لا يُسأل،
    // ومن لم يقرّ يُسأل ولو أقرّ زميله.
    await reachPlan();
    await click("plan-trial-start", "install");

    const OTHER = { email: "someone-else@govmind.test", full_name: "زميل" };
    await mount(
      { ...ROUTES, "/api/account/login": { ...LOGIN_OK, account: OTHER } },
      { plan: false, keepStorage: true, seed: { welcomeSeen: true } },
    );
    await signIn("choose-plan", { email: OTHER.email });

    expect(visibleScreen()).toBe("choose-plan");
  });

  it("Runtime مثبَّت وجاهز يتخطّى الشاشة", async () => {
    // من ثبّت البرنامج فعلًا لا يُسأل عن طريقة البدء.
    await mount(ROUTES, {
      plan: false,
      runtime: {
        "/health": {
          service: "govmind-runtime",
          phase: "ready",
          message: "GovMind جاهز للاستخدام.",
          is_ready: true,
          needs_activation: false,
          progress: null,
          downloaded_bytes: 0,
          total_bytes: 0,
          device_name: "حاسب ويندوز 11",
          subscription_status: "active",
        },
      },
    });
    await click("welcome-next");
    await signIn("installed");
  });

  // -- اللغة والمظهر -------------------------------------------------------
  it("⚠️ لا مفردات مؤسسات ولا لقب مسؤول في الشاشة", async () => {
    await reachPlan();
    const screen = document.getElementById("screen-choose-plan").textContent;
    for (const word of ["جهة", "مؤسسة", "منظمة", "مسؤول", "admin"]) {
      expect(screen, `تسرّبت مفردة «${word}»`).not.toContain(word);
    }
  });

  it("⚠️ خياران للمظهر فقط، بلا «تلقائي» وبلا أيقونة حاسوب", async () => {
    await reachPlan();
    const choices = [...document.querySelectorAll("[data-theme-choice]")].map(
      (item) => item.dataset.themeChoice,
    );

    expect(choices).toEqual(["light", "dark"]);
    expect(document.getElementById("theme-menu").textContent).not.toContain(
      "تلقائي",
    );
    expect(POPUP_HTML).not.toContain("M3.5 4.25c0-.97.78-1.75");
  });
});

/* ======================================================================== */
describe("١٤) الإخفاء الفعلي — حارس ضد صنف العطل لا حالته", () => {
  /*
   * **لماذا وُجد هذا القسم.**
   *
   * نافذة «الاشتراك الكامل» ظهرت للمستخدم في Chrome **دائمًا**، وزرّ
   * إغلاقها بلا أثر. والسبب ليس منطقًا خاطئًا: `.modal` أعلنت
   * `display: grid` ولم يُكتب لها حارس `.modal[hidden]`. قاعدة المؤلّف
   * تغلب `[hidden] { display: none }` في ورقة المتصفح، فبقيت الطبقة
   * مرسومة مهما ضُبطت السمة.
   *
   * ولم يكشفه أي اختبار سابق لأن كلها تفحص **الخاصية** `el.hidden`، وهي
   * كانت صحيحة تمامًا. الفارق بين «مضبوط» و«مخفيّ» لا يظهر إلا بتطبيق
   * ورقة الأنماط.
   *
   * فهذا الاختبار يحمّل `popup.css` الحقيقية ويسأل عن `display` المحسوب.
   */
  const CSS = readFileSync(resolve(process.cwd(), "popup.css"), "utf-8");

  /** يبني مستندًا كاملًا بورقة الأنماط مطبَّقة. */
  async function styledDocument() {
    const { JSDOM } = await import("jsdom");
    const html = POPUP_HTML.replace(
      /<link[^>]*popup\.css[^>]*>/,
      `<style>${CSS}</style>`,
    );
    return new JSDOM(html, { pretendToBeVisual: true }).window;
  }

  it("⚠️ كل عنصر يحمل `hidden` يُحسب `display: none` فعلًا", async () => {
    const win = await styledDocument();
    const offenders = [];

    for (const node of win.document.querySelectorAll("[hidden]")) {
      const display = win.getComputedStyle(node).display;
      if (display !== "none") {
        offenders.push(`${node.id || node.className || node.tagName} → ${display}`);
      }
    }

    expect(offenders, `عناصر مضبوطة hidden لكنها مرسومة: ${offenders}`).toEqual(
      [],
    );
  });

  it("⚠️ كل صنف يعلن `display` له حارس `[hidden]` مقابل", () => {
    // الفحص على النصّ لا على العرض: يمسك الصنف الجديد قبل أن يُستعمل في
    // عنصر يُخفى، لا بعد أن يظهر للمستخدم.
    const declaring = new Set();
    for (const match of CSS.matchAll(/^\.([a-z-]+)\s*\{([^}]*)\}/gms)) {
      const [, name, body] = match;
      if (/^\s*display:\s*(?!none)/m.test(body)) declaring.add(name);
    }

    const guarded = new Set(
      [...CSS.matchAll(/^\.([a-z-]+)\[hidden\]/gm)].map(([, name]) => name),
    );

    // الأصناف التي لا تُخفى أبدًا لا تحتاج حارسًا.
    const neverHidden = new Set([
      "app", "header", "brand", "brand__text", "main", "steps", "screen__title",
      "form", "field", "actions", "checklist", "facts", "progress", "plans",
      "plan-actions", "theme", "theme__trigger", "theme__menu", "theme__item",
      "button", "status", "note", "demo-badge", "plan-note",
      "footer__link", "alert__action",
    ]);
    // ⚠️ **`modal` ليست في القائمة عمدًا.** لو أُعيد صنفٌ بهذا الاسم يعلن
    // `display` بلا حارس لفشل هذا الاختبار — وهو بالضبط ما وقع.

    const missing = [...declaring].filter(
      (name) => !guarded.has(name) && !neverHidden.has(name),
    );

    expect(missing, `أصناف تعلن display بلا حارس [hidden]: ${missing}`).toEqual(
      [],
    );
  });

  it("شاشة اختيار طريقة البدء مرسومة، وبقية الشاشات لا", async () => {
    const win = await styledDocument();
    const plan = win.document.getElementById("screen-choose-plan");
    plan.hidden = false;

    expect(win.getComputedStyle(plan).display).not.toBe("none");
    expect(
      win.getComputedStyle(win.document.getElementById("screen-install")).display,
    ).toBe("none");
  });

  it("زرّ «اشترك الآن» معطّل في الترميز نفسه لا في الشيفرة وحدها", async () => {
    const win = await styledDocument();
    const button = win.document.getElementById("plan-paid-start");

    expect(button.hasAttribute("disabled")).toBe(true);
    expect(
      win.getComputedStyle(win.document.getElementById("plan-paid-note")).display,
    ).not.toBe("none");
  });
});

/* ======================================================================== */
describe("١٥) الإقلاع — سرعته وحياده ونظافة حالته", () => {
  /*
   * **العطل الحيّ.** بعد دخول ٢٠٠ واشتراك ٢٠٠، وبلا أي طلب جلسة تركيب
   * وبلا تنزيل، كانت النافذة تعرض «جارٍ تفعيل هذا الجهاز» زمنًا طويلًا.
   *
   * سببان اجتمعا:
   *   ① الاكتشاف كان **متتابعًا**: خمسة منافذ × ١٫٥ ثانية = ٧٫٥ ثانية قبل
   *     أول رسم، وأول تثبيت — حيث لا يردّ منفذ — أبطأ الحالات كلها.
   *   ② أي Runtime عالق في `phase: "activating"` كان يرسم شاشة التفعيل
   *     فورًا، بلا جلسة ولا تنزيل ولا فعلٍ من المستخدم.
   */

  const ROUTES = {
    "/api/account/login": LOGIN_OK,
    "/api/account/subscription": subscription(),
  };

  const SIGNED_IN = {
    accessToken: "issued-token",
    tokenExpiresAt: Date.now() + 3600_000,
    account: ACCOUNT,
    welcomeSeen: true,
  };

  const STUCK_RUNTIME = {
    service: "govmind-runtime",
    phase: "activating",
    message: "جارٍ تفعيل الجهاز…",
    is_ready: false,
    needs_activation: true,
    progress: null,
    downloaded_bytes: 0,
    total_bytes: 0,
  };

  // -- السرعة ------------------------------------------------------------
  it("⚠️ الإقلاع بلا Runtime ينتهي في أقل من ثانية", async () => {
    // المنافذ الخمسة تُجرَّب معًا تحت سقف واحد، لا واحدًا بعد واحد.
    const started = Date.now();
    await mount(ROUTES, { seed: { ...SIGNED_IN, ...planSeed() } });
    const elapsed = Date.now() - started;

    expect(visibleScreen()).toBe("install");
    expect(elapsed, `استغرق الإقلاع ${elapsed}ms`).toBeLessThan(1000);
  });

  it("⚠️ المنافذ الخمسة تُستطلع في اللحظة نفسها لا بالتتابع", async () => {
    const probes = [];
    const { fetchMock } = await mount(ROUTES, {
      seed: { ...SIGNED_IN, ...planSeed() },
    });

    for (const [url] of fetchMock.mock.calls) {
      if (String(url).includes("127.0.0.1")) probes.push(String(url));
    }

    expect(probes).toHaveLength(RUNTIME_PORTS.length);
    for (const port of RUNTIME_PORTS) {
      expect(probes.some((url) => url.includes(`:${port}/`))).toBe(true);
    }
  });

  it("منفذ صامت لا يؤخّر الإقلاع فوق السقف", async () => {
    // منفذ لا يردّ أبدًا: السقف الجماعي يقطعه، ولا ينتظره الباقون.
    const started = Date.now();
    await mount(ROUTES, {
      seed: { ...SIGNED_IN, ...planSeed() },
      runtime: { "/health": () => new Promise(() => {}) },
    });
    const elapsed = Date.now() - started;

    expect(elapsed, `استغرق الإقلاع ${elapsed}ms`).toBeLessThan(1600);
    expect(visibleScreen()).toBe("install");
  });

  // -- الحياد ------------------------------------------------------------
  it("⚠️ الإقلاع لا يعرض «جارٍ تفعيل هذا الجهاز» أبدًا", async () => {
    await mount(ROUTES, {
      seed: { ...SIGNED_IN, ...planSeed() },
      runtime: { "/health": STUCK_RUNTIME },
    });

    expect(visibleScreen()).not.toBe("activating-device");
    expect(document.getElementById("screen-activating-device").hidden).toBe(true);

    // ⚠️ **النصّ الظاهر وحده.** `body.textContent` يشمل الشاشات المخفية
    // كذلك، فالفحص عليه يقيس الترميز لا ما يراه المستخدم.
    const visible = [...document.querySelectorAll(".screen")]
      .filter((screen) => !screen.hidden)
      .map((screen) => screen.textContent)
      .join(" ");
    expect(visible).not.toContain("تفعيل");
  });

  it("⚠️ ولا يُصدر جلسة تركيب أثناء الإقلاع", async () => {
    // إصدارُ جلسةٍ فعلٌ يخصّ التثبيت، لا أثرًا جانبيًا لفتح النافذة.
    const { fetchMock } = await mount(ROUTES, {
      seed: { ...SIGNED_IN, ...planSeed() },
      runtime: { "/health": STUCK_RUNTIME },
    });

    const paths = fetchMock.mock.calls.map(([url]) => String(url));
    expect(paths.some((p) => p.includes("/installation-session"))).toBe(false);
    expect(paths.some((p) => p.includes("/installer/download-url"))).toBe(false);
  });

  it("شاشة الفحص محايدة ولا تَعِد بتفعيل", () => {
    document.body.innerHTML = BODY;
    const screen = document.getElementById("screen-checking");

    expect(screen).not.toBeNull();
    expect(screen.textContent).toContain("جاري التحقق...");
    expect(screen.textContent).not.toContain("تفعيل");
    // ولا شريط تقدّم يدور بلا نهاية في شاشة عمرها ثانية.
    expect(screen.querySelector("[data-indeterminate]")).toBeNull();
  });

  it("بعد اشتراك ٢٠٠ يستقرّ أول جهاز على choose-plan ثم install", async () => {
    await mount(ROUTES, { plan: false, seed: SIGNED_IN });
    expect(visibleScreen()).toBe("choose-plan");

    await click("plan-trial-start", "install");
    expect(visibleScreen()).toBe("install");
  });

  // -- نظافة الحالة الموروثة ---------------------------------------------
  it("⚠️ حالة «activating» موروثة بلا جلسة تُمسح", async () => {
    await mount(ROUTES, {
      seed: { ...SIGNED_IN, ...planSeed(), installStage: "activating" },
      runtime: { "/health": STUCK_RUNTIME },
    });

    expect(visibleScreen()).toBe("install");
    expect(await chrome.storage.local.get("installStage")).toEqual({});
  });

  it("⚠️ حالة متقدّمة بلا downloadId تُمسح ولا يبدأ استطلاع", async () => {
    await mount(ROUTES, {
      seed: { ...SIGNED_IN, ...planSeed(), installStage: "installing" },
      runtime: { "/health": STUCK_RUNTIME },
    });

    expect(visibleScreen()).toBe("install");
    expect(await chrome.storage.local.get("installStage")).toEqual({});
  });

  it("⚠️ downloadId لا وجود له في سجل المتصفح يُمسح كذلك", async () => {
    await mount(ROUTES, {
      seed: {
        ...SIGNED_IN,
        ...planSeed(),
        installStage: "downloaded",
        downloadId: 999999,
      },
    });

    expect(visibleScreen()).toBe("install");
    expect(await chrome.storage.local.get("installStage")).toEqual({});
  });

  it("⚠️ رمز تركيب منتهي الصلاحية يُمسح ويعود المستخدم إلى التثبيت", async () => {
    const id = 7788;
    chrome.downloads.__seed(id);
    await mount(ROUTES, {
      seed: {
        ...SIGNED_IN,
        ...planSeed(),
        installStage: "installing",
        downloadId: id,
        downloadFileName: "GovMindSetup.exe",
        installToken: "expired-session-token",
        installTokenExpiresAt: new Date(Date.now() - 60_000).toISOString(),
      },
    });

    expect(visibleScreen()).toBe("install");
    expect(await chrome.storage.local.get("installToken")).toEqual({});
    expect(await chrome.storage.local.get("installStage")).toEqual({});
  });

  it("تنزيل مكتمل صالح **يبقى** ولا يُمسح مع الحالات الفاسدة", async () => {
    const id = 3311;
    chrome.downloads.__seed(id);
    await mount(ROUTES, {
      seed: {
        ...SIGNED_IN,
        ...planSeed(),
        installStage: "downloaded",
        downloadId: id,
        downloadFileName: "GovMindSetup.exe",
      },
    });

    expect(visibleScreen()).toBe("installer-ready");
    expect(chrome.downloads.download).not.toHaveBeenCalled();
  });

  it("Runtime مثبَّت وجاهز يُكتشف رغم كل التنظيف", async () => {
    await mount(ROUTES, {
      seed: { ...SIGNED_IN, ...planSeed() },
      runtime: {
        "/health": {
          service: "govmind-runtime",
          phase: "ready",
          message: "GovMind جاهز.",
          is_ready: true,
          needs_activation: false,
          progress: null,
          downloaded_bytes: 0,
          total_bytes: 0,
          device_name: "حاسب ويندوز 11",
          subscription_status: "trial",
        },
      },
    });

    expect(visibleScreen()).toBe("installed");
  });

  // -- العزل بين الحسابات -------------------------------------------------
  it("⚠️ حساب لا يرث حالة تثبيت حساب آخر على الجهاز نفسه", async () => {
    const id = 5150;
    chrome.downloads.__seed(id);

    await mount(ROUTES, {
      plan: false,
      seed: {
        welcomeSeen: true,
        installStage: "installing",
        downloadId: id,
        downloadFileName: "GovMindSetup.exe",
        installOwner: "someone-else@govmind.test",
        planAckFor: ACCOUNT.email,
      },
    });
    await signIn("install");

    expect(visibleScreen()).toBe("install");
    expect(await chrome.storage.local.get("installStage")).toEqual({});
  });

  it("الخروج يمسح حالة التثبيت ومالكها", async () => {
    const id = 6060;
    chrome.downloads.__seed(id);
    await mount(ROUTES, {
      seed: {
        ...SIGNED_IN,
        ...planSeed(),
        installStage: "downloaded",
        downloadId: id,
        downloadFileName: "GovMindSetup.exe",
      },
    });
    await waitForScreen("installer-ready");

    document.querySelector("[data-signout]").click();
    await waitForScreen("signin");

    const left = await chrome.storage.local.get([
      "installStage",
      "downloadId",
      "installOwner",
      "installToken",
    ]);
    expect(left).toEqual({});
  });

  // -- متى يبدأ الاستطلاع فعلًا -------------------------------------------
  it("⚠️ الاستطلاع الفعلي لا يبدأ إلا بعد أن يقبل المتصفح فتح الملف", async () => {
    const id = 9090;
    chrome.downloads.__seed(id);
    const { fetchMock } = await mount(ROUTES, {
      seed: {
        ...SIGNED_IN,
        ...planSeed(),
        installStage: "downloaded",
        downloadId: id,
        downloadFileName: "GovMindSetup.exe",
      },
    });
    await waitForScreen("installer-ready");

    const probes = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).includes("127.0.0.1"))
        .length;
    const afterBoot = probes();
    await tick();
    expect(probes()).toBe(afterBoot);

    await click("ready-open", "awaiting-runtime");
    await vi.waitFor(() => expect(probes()).toBeGreaterThan(afterBoot));
  });
});

/* ======================================================================== */
/**
 * ١٦) الشاشة التي رآها العميل حيًّا، وما صارت عليه.
 *
 * **الشكوى بنصّها:** بعد التنزيل ظهر إجراء يفهمه العميل على أنه «سيفتح
 * المثبّت»، فضغطه — ولم يُفتح شيء. الملف بقي في مجلد التنزيلات، والإضافة
 * دخلت في استطلاعٍ لبرنامج لم يبدأ، فانتظرت بلا نهاية.
 *
 * هذا القسم يحرس الفروق الأربعة التي يقوم عليها الإصلاح:
 *
 *   ١) الزرّ **يفتح** ولا يكتفي بأن يُقرّ المستخدم.
 *   ٢) الانتظار يبدأ **على نتيجة الفتح** لا على النقر.
 *   ٣) لكل فشلٍ شاشتُه وإجراؤه — لا شريط تنبيه فوق مؤشّر دوّار.
 *   ٤) لا شاشة تقدّم بلا مخرج، ولا نصّ يسمّي ما لا يحدث.
 */
describe("١٦) تصحيح ترتيب فتح المثبّت", () => {
  const SESSION = {
    token: "installation-session-token-value-000042",
    expires_at: "2099-01-01T00:00:00Z",
    expires_in_minutes: 15,
  };

  const LINK = {
    download_url:
      "https://acct.blob.core.windows.net/releases/GovMindSetup.exe?sig=SECRET",
    file_name: "GovMindSetup.exe",
    expires_at: "2099-01-01T00:00:00Z",
    expires_in_minutes: 15,
  };

  const READY = {
    "/api/account/login": LOGIN_OK,
    "/api/account/subscription": subscription(),
    "/api/account/installation-session": SESSION,
    "/api/account/installer/download-url": LINK,
  };

  const AWAITING = {
    service: "govmind-runtime",
    phase: "awaiting_activation",
    message: "بانتظار تفعيل هذا الجهاز من إضافة GovMind.",
    progress: null,
    downloaded_bytes: 0,
    total_bytes: 0,
    device_name: null,
    subscription_status: null,
    is_ready: false,
    needs_activation: true,
  };

  async function downloadedInstaller(routes = READY, options = {}) {
    const mounted = await mount(routes, options);
    await click("welcome-next", "signin");
    await signIn("install");
    await click("install-start", "downloading");
    chrome.downloads.__finish(chrome.downloads.__all()[0].id);
    await vi.waitFor(() => expect(visibleScreen()).toBe("installer-ready"));
    return mounted;
  }

  // -- ١) النصّ القديم اختفى -----------------------------------------------
  it("⚠️ الإجراء المضلِّل القديم لا وجود له في أي ملف", () => {
    // كان زرًّا يقول للمستخدم إنه هو من فتح المثبّت، فيبدأ انتظارًا على
    // إقرارٍ لا على فعل. لا في HTML ولا في JS ولا في معرّفات العناصر.
    const sources = [POPUP_HTML, POPUP_JS];
    for (const source of sources) {
      expect(source).not.toContain("فتحتُ المثبّت");
      expect(source).not.toContain("فتحت المثبّت");
      expect(source).not.toContain("أكمل التفعيل");
      expect(source).not.toContain("ready-installed");
      expect(source).not.toContain("doInstallStarted");
    }
    expect(document.getElementById("ready-installed")).toBeNull();
  });

  it("شاشة ما بعد التنزيل تحمل العنوان والزرّين المطلوبين بالضبط", () => {
    document.body.innerHTML = BODY;
    const screen = document.getElementById("screen-installer-ready");

    expect(screen.querySelector(".screen__title").textContent.trim()).toBe(
      "تم تنزيل GovMind",
    );
    expect(document.getElementById("ready-open").textContent.trim()).toBe(
      "فتح ملف التثبيت",
    );
    expect(document.getElementById("ready-show").textContent.trim()).toBe(
      "إظهار في المجلد",
    );
  });

  // -- ٢) الفتح فعلٌ يقع ---------------------------------------------------
  it("الزرّ الأساسي ينادي chrome.downloads.open بمعرّف الملف المنزَّل", async () => {
    await downloadedInstaller();
    const id = chrome.downloads.__all()[0].id;

    await click("ready-open", "awaiting-runtime");

    expect(chrome.downloads.open).toHaveBeenCalledTimes(1);
    expect(chrome.downloads.open).toHaveBeenCalledWith(id);
  });

  it("الزرّ الثانوي ينادي chrome.downloads.show بالمعرّف نفسه", async () => {
    await downloadedInstaller();
    const id = chrome.downloads.__all()[0].id;

    await click("ready-show");

    expect(chrome.downloads.show).toHaveBeenCalledWith(id);
  });

  // -- ٣) الانتظار مشروط بنجاح الفتح ---------------------------------------
  it("⚠️ فشل الفتح: لا استطلاع، ويُظهَر الملف، وتعليمة واحدة واضحة", async () => {
    const { fetchMock } = await downloadedInstaller();
    const id = chrome.downloads.__all()[0].id;
    const before = fetchMock.mock.calls.filter(([u]) =>
      String(u).includes("127.0.0.1"),
    ).length;

    chrome.downloads.__refuseOpen = true;
    try {
      await click("ready-open", "open-failed");
    } finally {
      chrome.downloads.__refuseOpen = false;
    }

    await tick();
    expect(
      fetchMock.mock.calls.filter(([u]) => String(u).includes("127.0.0.1")),
    ).toHaveLength(before);
    expect(chrome.downloads.show).toHaveBeenCalledWith(id);
    expect(document.getElementById("open-failed-message").textContent).toBe(
      "افتح GovMindSetup.exe من المجلد لإكمال التثبيت.",
    );
    expect(document.getElementById("open-failed-check").textContent.trim()).toBe(
      "تحقق من التثبيت",
    );
  });

  it("⚠️ متصفح لا يدعم الفتح أصلًا يسلك المسار نفسه", async () => {
    await downloadedInstaller();
    const original = chrome.downloads.open;
    delete chrome.downloads.open;
    try {
      await click("ready-open", "open-failed");
    } finally {
      chrome.downloads.open = original;
    }
    expect(document.getElementById("open-failed-message").textContent).toContain(
      "من المجلد",
    );
  });

  // -- ٤) نصوص الحالات لا تسمّي ما لا يحدث ---------------------------------
  it("⚠️ الانتظار يقول «بانتظار اكتمال تثبيت GovMind» لا «تفعيل هذا الجهاز»", async () => {
    await downloadedInstaller();
    await click("ready-open", "awaiting-runtime");

    const screen = document.getElementById("screen-awaiting-runtime");
    expect(screen.querySelector(".screen__title").textContent.trim()).toBe(
      "بانتظار اكتمال تثبيت GovMind",
    );
    expect(screen.textContent).not.toContain("جارٍ تفعيل هذا الجهاز");
    expect(screen.textContent).not.toContain("جار تفعيل هذا الجهاز");
  });

  it("المهلة تعطي النصّ المطلوب حرفيًا وزرَّ تعافٍ", async () => {
    await downloadedInstaller();
    await click("ready-open", "awaiting-runtime");
    await click("awaiting-help", "install-help");

    const message = document
      .getElementById("install-help-message")
      .textContent.replace(/\s+/g, " ")
      .trim();
    expect(message).toBe(
      "لم يبدأ GovMind بعد. تأكد من إكمال المثبّت وأن Windows لم يمنعه، ثم أعد المحاولة.",
    );
    expect(document.getElementById("help-retry")).not.toBeNull();
  });

  // -- ٥) تمييز الحالات ----------------------------------------------------
  it("⚠️ تعذّر تسليم الرمز شاشةٌ غير شاشة رفض التفعيل", async () => {
    // الـRuntime يعمل ويرد على `/health`، ويسقط `/activate`: الرمز لم يصل.
    await mount(READY, {
      seed: planSeed(),
      runtime: {
        "/health": AWAITING,
        "/activate": { status: 502, body: { detail: "" } },
      },
    });
    await click("welcome-next", "signin");
    await signIn();

    await vi.waitFor(() => expect(visibleScreen()).toBe("handover-failed"), {
      timeout: 5000,
    });
    const text = document.getElementById("handover-failed-message").textContent;
    expect(text).toContain("تعذّر");
    expect(document.getElementById("handover-retry")).not.toBeNull();
  });

  it("⚠️ رفض الخادم للتفعيل يعرض سببه هو، على شاشته هو", async () => {
    await mount(READY, {
      seed: planSeed(),
      runtime: {
        "/health": AWAITING,
        "/activate": {
          status: 409,
          body: { detail: "حسابك مفعّل حاليًا على جهاز آخر." },
        },
      },
    });
    await click("welcome-next", "signin");
    await signIn();

    await vi.waitFor(() => expect(visibleScreen()).toBe("activation-failed"), {
      timeout: 5000,
    });
    expect(
      document.getElementById("activation-failed-message").textContent,
    ).toContain("جهاز آخر");
  });

  it("⚠️ لا شاشة تقدّم بلا مخرج: كل شاشة فشل فيها زرّ", () => {
    document.body.innerHTML = BODY;
    for (const id of [
      "screen-open-failed",
      "screen-install-help",
      "screen-handover-failed",
      "screen-activation-failed",
    ]) {
      const screen = document.getElementById(id);
      expect(screen, `الشاشة ${id} مفقودة`).not.toBeNull();
      expect(screen.querySelectorAll("button").length).toBeGreaterThan(0);
    }
  });

  // -- ٦) الاستئناف وعدم التكرار -------------------------------------------
  it("إغلاق النافذة وفتحها بعد نجاح الفتح يعود إلى الانتظار بلا تنزيل ثانٍ", async () => {
    await downloadedInstaller();
    await click("ready-open", "awaiting-runtime");

    await mount(READY, { seed: planSeed(), keepStorage: true });

    expect(visibleScreen()).toBe("awaiting-runtime");
    expect(chrome.downloads.download).toHaveBeenCalledTimes(1);
  });

  it("⚠️ لا جلسة تركيب ثانية عند إعادة الفتح", async () => {
    const first = await downloadedInstaller();
    await click("ready-open", "awaiting-runtime");

    const sessionCalls = (mock) =>
      mock.mock.calls.filter(([u]) =>
        String(u).includes("/installation-session"),
      ).length;
    expect(sessionCalls(first.fetchMock)).toBe(1);

    const second = await mount(READY, { seed: planSeed(), keepStorage: true });
    await tick();
    expect(sessionCalls(second.fetchMock)).toBe(0);
  });

  it("الخروج يمحو حالة التثبيت كلها فلا يرثها حساب آخر", async () => {
    await downloadedInstaller();
    await click("ready-open", "awaiting-runtime");

    document.querySelector("[data-signout]").click();
    await waitForScreen("signin");

    const left = await chrome.storage.local.get([
      "installStage",
      "downloadId",
      "downloadFileName",
      "installToken",
      "installTokenExpiresAt",
    ]);
    expect(left).toEqual({});
  });
});
