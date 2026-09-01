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

// المسار من جذر المشروع لا من `import.meta.url`: في بيئة jsdom لا يكون
// الأخير رابط ملف، فـ`fileURLToPath` ترفض.
const POPUP_HTML = readFileSync(resolve(process.cwd(), "popup.html"), "utf-8");

/** جسم `popup.html` وحده — الرأس يحمل وسوم سكربتات لا تُنفَّذ هنا. */
const BODY = POPUP_HTML.split("<body>")[1].split("</body>")[0];

const ACCOUNT = {
  email: "employee@govmind.test",
  full_name: "موظف",
  role: "employee",
  organization_id: 1,
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
async function mount(routes, { seed, runtime } = {}) {
  await chrome.storage.local.remove([
    "accessToken",
    "refreshToken",
    "tokenExpiresAt",
    "account",
    "deviceId",
    "deviceName",
    "welcomeSeen",
  ]);
  if (seed) await chrome.storage.local.set(seed);
  document.body.innerHTML = BODY;
  const fetchMock = routeFetch(routes, runtime);
  vi.stubGlobal("fetch", fetchMock);

  vi.resetModules();
  const module = await import("../popup.js");
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
    document.body.innerHTML = BODY;
    for (const input of document.querySelectorAll("input")) {
      expect(["email", "password"]).toContain(input.type);
    }
    expect(POPUP_HTML).not.toContain("apiBaseUrl");
    expect(POPUP_HTML.toLowerCase()).not.toContain("api key");
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
    await signIn("activate");

    expect(document.getElementById("signin-password").value).toBe("");
  });
});

describe("٢) حساب بلا جهة", () => {
  it("يعرض «راجع مسؤول النظام» بلا محاولة قراءة الاشتراك", async () => {
    const { fetchMock } = await mount({
      "/api/account/login": { ...LOGIN_OK, account: null },
    });
    await click("welcome-next", "signin");
    await signIn("not-provisioned");

    // لا معنى لسؤال عن اشتراك جهةٍ لا ينتمي إليها الحساب.
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
  it("يعرض شاشة التفعيل حين لا جهاز مفعّلًا", async () => {
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription(),
    });
    await click("welcome-next", "signin");
    await signIn("activate");

    expect(document.getElementById("activate-facts").textContent).toContain(
      ACCOUNT.email,
    );
  });

  it("التفعيل ينقل إلى شاشة التثبيت ويرسل بصمة وaسمًا", async () => {
    let activatePayload = null;
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription(),
      "/api/account/devices/activate": (body) => {
        activatePayload = body;
        return subscription({ device: ACTIVE_DEVICE, requires_activation: false });
      },
    });
    await click("welcome-next", "signin");
    await signIn("activate");
    await click("activate-submit", "install");

    expect(activatePayload.device_id.length).toBeGreaterThanOrEqual(16);
    expect(activatePayload.device_name).toBeTruthy();
  });

  it("يعرض «مفعّل على جهاز آخر» ويسمّي الجهاز", async () => {
    const other = { ...ACTIVE_DEVICE, device_name: "حاسب المنزل" };
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription({ device: other }),
      "/api/account/devices/verify": {
        status: 409,
        body: {
          detail: "حسابك مفعّل على جهاز آخر (حاسب المنزل).",
          code: "conflict",
        },
      },
    });
    await click("welcome-next", "signin");
    await signIn("device-taken");

    expect(document.getElementById("device-taken-message").textContent).toContain(
      "حاسب المنزل",
    );
  });

  it("رفض التفعيل بـ٤٠٩ ينقل إلى شاشة «جهاز آخر» بلا زر إجراء", async () => {
    // سباق حقيقي: عند الدخول لم يكن أي جهاز مفعّلًا، فعُرضت شاشة التفعيل.
    // ثم سبق جهاز آخر بين العرض والضغط، فترفض القاعدة التفعيل بـ٤٠٩.
    let subscriptionCalls = 0;
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": () =>
        subscriptionCalls++ === 0
          ? subscription()
          : subscription({ device: { ...ACTIVE_DEVICE, is_current_device: false } }),
      "/api/account/devices/activate": {
        status: 409,
        body: { detail: "حسابك مفعّل بالفعل على جهاز آخر.", code: "conflict" },
      },
      "/api/account/devices/verify": {
        status: 409,
        body: { detail: "حسابك مفعّل على جهاز آخر.", code: "conflict" },
      },
    });
    await click("welcome-next", "signin");
    await signIn("activate");
    await click("activate-submit", "device-taken");

    // لا زرّ «أعد المحاولة»: الحل عند مسؤول النظام لا هنا.
    expect(document.getElementById("alert-action").hidden).toBe(true);
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
    await mount(ready);
    await click("welcome-next");
    await signIn("install");
  }

  it("يعرض شاشة التثبيت لجهاز مفعّل واشتراك سليم", async () => {
    await reachInstall();
    expect(document.getElementById("install-facts").textContent).toContain(
      "حاسب المكتب",
    );
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

  it("بعد اكتمال التنزيل يطلب فتح المثبّت وينتظر ظهور GovMind", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    const id = chrome.downloads.__all()[0].id;
    chrome.downloads.__finish(id);
    await tick();

    await vi.waitFor(() => expect(visibleScreen()).toBe("awaiting-runtime"));
    expect(document.getElementById("awaiting-file-name").textContent).toBe(
      "GovMindSetup.exe",
    );
    const text = document.getElementById("screen-awaiting-runtime").textContent;
    expect(text).toContain("افتح الملف");
    expect(text).toContain("نافذة ويندوز");
  });

  it("⚠️ لا تشغّل الإضافة الملف: «أظهر» يفتح المجلد وحده", async () => {
    await reachInstall();
    await click("install-start", "downloading");

    const id = chrome.downloads.__all()[0].id;
    chrome.downloads.__finish(id);
    await tick();
    await vi.waitFor(() => expect(visibleScreen()).toBe("awaiting-runtime"));

    document.getElementById("awaiting-show").click();
    expect(chrome.downloads.show).toHaveBeenCalledWith(id);
    // `chrome.downloads.open` هو ما يشغّل الملف، ولا وجود له في الشيفرة.
    expect(chrome.downloads.open).toBeUndefined();
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
    expect(alertText()).toContain("انتهت جلستك");
  });

  it("الخروج يمسح الجلسة ويعود إلى الدخول لا إلى الترحيب", async () => {
    await mount({
      "/api/account/login": LOGIN_OK,
      "/api/account/subscription": subscription(),
    });
    await click("welcome-next", "signin");
    await signIn("activate");

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
    await signIn("activate");

    expect(document.getElementById("footer").hidden).toBe(false);
    expect(document.getElementById("footer-account").textContent).toBe(
      ACCOUNT.email,
    );
  });
});

describe("٧) المظهر — ثلاثة خيارات في الإضافة", () => {
  it("يعرض فاتح وداكن وتلقائي", async () => {
    await mount({});
    const choices = [...document.querySelectorAll("[data-theme-choice]")].map(
      (item) => item.dataset.themeChoice,
    );
    expect(choices).toEqual(["light", "dark", "system"]);
  });

  it("اختيار «داكن» يطبّقه ويحفظه", async () => {
    await mount({});
    document.querySelector('[data-theme-choice="dark"]').click();

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("govagent.theme")).toBe("dark");
  });

  it("«تلقائي» يتبع الجهاز ولا يُخزَّن كوضع صريح", async () => {
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      addEventListener: () => {},
    }));
    await mount({});
    document.querySelector('[data-theme-choice="system"]').click();

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("govagent.theme")).toBe("system");
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
    await click("welcome-next");

    // ⚠️ **بلا أي ضغطة**: Runtime ينتظر التفعيل، فتُصدر الإضافة رمزًا
    // وتسلّمه تلقائيًا. الشرط صريح: لا ينسخ المستخدم رمزًا ولا يلصقه.
    await vi.waitFor(() => expect(received).not.toBeNull(), { timeout: 4000 });
    expect(received.token).toBe("installation-session-token-value-000001");

    // ينتهي المسار عند «جارٍ التجهيز»: التفعيل مرحلة عابرة بين الشاشتين.
    await vi.waitFor(() => expect(visibleScreen()).toBe("preparing-model"), {
      timeout: 4000,
    });
  });

  it("يعرض تقدّم تنزيل المودل بالعربية", async () => {
    await mount(signedInRoutes, { runtime: { "/health": DOWNLOADING } });
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
    await mount(signedInRoutes, { runtime: { "/health": DOWNLOADING } });
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
        runtime: {
          "/health": () => phase,
          "/activate": () => {
            phase = DOWNLOADING;
            return DOWNLOADING;
          },
        },
      },
    );
    await click("welcome-next");
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
    await waitForAlert("جهاز آخر");
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
