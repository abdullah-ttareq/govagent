/**
 * عميل الـAPI، والتخزين، وبصمة الجهاز، وترجمة الأخطاء.
 *
 * أهم ما يثبته هذا الملف: **الإضافة لا تطلب من المستخدم رابطًا ولا مفتاحًا،
 * ولا تنادي Supabase ولا Azure**، وأنها تنادي عنوان البناء الثابت وحده.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BACKEND_URL } from "../config.js";
import {
  ApiError,
  NetworkError,
  fetchSubscription,
  login,
  requestInstallerUrl,
  verifyDevice,
} from "../lib/api.js";
import { describeFailure, actionLabel } from "../lib/errors.js";
import { describePlatform, ensureDeviceId, ensureDeviceName } from "../lib/device.js";
import {
  clearSession,
  getDeviceId,
  getSession,
  getWelcomeSeen,
  isSessionUsable,
  pruneLegacyKeys,
  setSession,
  setWelcomeSeen,
} from "../lib/storage.js";

let fetchMock;

beforeEach(() => {
  fetchMock = vi.fn(async () =>
    new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastRequest() {
  const [url, options] = fetchMock.mock.lastCall;
  return { url, options, body: options.body ? JSON.parse(options.body) : null };
}

describe("عنوان ثابت وقت البناء", () => {
  it("كل طلب يذهب إلى عنوان الـBackend وحده", async () => {
    await login("a@b.test", "secret");
    expect(lastRequest().url).toBe(`${BACKEND_URL}/api/account/login`);
  });

  it("لا تنادي الإضافة Supabase ولا Azure مباشرة", async () => {
    await login("a@b.test", "secret");
    await fetchSubscription("token");
    await verifyDevice("token", "device-1234");
    await requestInstallerUrl("token", "device-1234");

    for (const [url] of fetchMock.mock.calls) {
      expect(url.startsWith(BACKEND_URL)).toBe(true);
      expect(url).not.toContain("supabase");
      expect(url).not.toContain("blob.core.windows.net");
    }
  });

  it("طلب الدخول يحمل البريد وكلمة المرور فقط", async () => {
    await login("a@b.test", "secret");
    // **لا حقل لرابط ولا لمفتاح API ولا لمعرّف جهة.**
    expect(Object.keys(lastRequest().body)).toEqual(["email", "password"]);
  });

  it("يرسل الرمز في ترويسة Authorization لا في الرابط", async () => {
    await fetchSubscription("the-token");
    const { url, options } = lastRequest();
    expect(options.headers.Authorization).toBe("Bearer the-token");
    expect(url).not.toContain("the-token");
  });

  it("بصمة الجهاز تُرسل في جسم POST لا في رابط GET", async () => {
    await verifyDevice("token", "device-1234");
    const { url, options, body } = lastRequest();
    expect(options.method).toBe("POST");
    expect(body.device_id).toBe("device-1234");
    // في الرابط تدخل سجلات السيرفر والوسطاء.
    expect(url).not.toContain("device-1234");
  });
});

describe("معالجة أخطاء الشبكة والـAPI", () => {
  it("فشل الوصول يصير NetworkError برسالة عربية", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(fetchSubscription("token")).rejects.toBeInstanceOf(NetworkError);
  });

  it("رد الخطأ يحمل رسالة السيرفر ورمز الحالة", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "انتهى اشتراكك بتاريخ ٢٠٢٦-٠١-٠١.", code: "forbidden" }),
        { status: 403, headers: { "content-type": "application/json" } },
      ),
    );

    await expect(fetchSubscription("token")).rejects.toMatchObject({
      status: 403,
      message: "انتهى اشتراكك بتاريخ ٢٠٢٦-٠١-٠١.",
    });
  });

  it("جسم غير صالح لا يُسقط النافذة", async () => {
    fetchMock.mockResolvedValueOnce(new Response("not json", { status: 500 }));
    await expect(fetchSubscription("token")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("ترجمة الفشل إلى رسالة وإجراء", () => {
  it("٤٠١ تعني سقوط الجلسة وتعرض زر دخول", () => {
    const failure = describeFailure(new ApiError("منتهٍ", 401, "unauthorized"));
    expect(failure.sessionLost).toBe(true);
    expect(failure.action).toBe("signin");
    expect(actionLabel(failure.action)).toBe("تسجيل الدخول");
  });

  it("٤٠٣ تعرض رسالة السيرفر كما هي بلا زر", () => {
    const detail = "انتهى اشتراكك بتاريخ ٢٠٢٦-٠١-٠١. راجع مسؤول النظام.";
    const failure = describeFailure(new ApiError(detail, 403, "forbidden"));
    expect(failure.message).toBe(detail);
    expect(failure.action).toBe("none");
    expect(actionLabel(failure.action)).toBeNull();
  });

  it("٤٠٩ «جهاز آخر» بلا زر: الحل عند المسؤول لا هنا", () => {
    const failure = describeFailure(
      new ApiError("حسابك مفعّل بالفعل على جهاز آخر.", 409, "conflict"),
    );
    expect(failure.action).toBe("none");
    expect(failure.sessionLost).toBe(false);
  });

  it("لا إجراء «إعدادات» ولا «إذن نطاق» بعد إزالة شاشة الرابط", () => {
    const actions = [401, 403, 404, 409, 429, 500, 503].map(
      (status) => describeFailure(new ApiError("م", status, "c")).action,
    );
    expect(actions).not.toContain("settings");
    expect(actions).not.toContain("permission");
  });
});

describe("التخزين", () => {
  it("يحفظ الجلسة بلحظة انتهاء مطلقة", async () => {
    await setSession({
      accessToken: "t",
      refreshToken: "r",
      expiresIn: 3600,
      account: { email: "a@b.test" },
    });

    const session = await getSession();
    expect(session.token).toBe("t");
    expect(session.expiresAt).toBeGreaterThan(Date.now());
    expect(isSessionUsable(session)).toBe(true);
  });

  it("الجلسة المنتهية غير صالحة", () => {
    expect(isSessionUsable({ token: "t", expiresAt: Date.now() - 1 })).toBe(false);
    expect(isSessionUsable(null)).toBe(false);
  });

  it("الخروج يمسح الرمز ويبقي بصمة الجهاز", async () => {
    await setSession({ accessToken: "t", expiresIn: 3600, account: {} });
    const deviceId = await ensureDeviceId();

    await clearSession();

    expect(await getSession()).toBeNull();
    // البصمة صفة للجهاز لا للمستخدم: تغييرها عند كل خروج يجعل الجهاز
    // يبدو جديدًا فيصطدم صاحبه برسالة «مفعّل على جهاز آخر» على جهازه.
    expect(await getDeviceId()).toBe(deviceId);
  });

  it("يمسح مفاتيح الإصدارات السابقة ومنها رابط السيرفر", async () => {
    await chrome.storage.local.set({
      apiBaseUrl: "http://old-server:9000",
      conversationId: 7,
      user: { name: "قديم" },
    });

    await pruneLegacyKeys();

    const remaining = await chrome.storage.local.get([
      "apiBaseUrl",
      "conversationId",
      "user",
    ]);
    expect(remaining).toEqual({});
  });

  it("علامة الترحيب تبقى بعد أول مرة", async () => {
    expect(await getWelcomeSeen()).toBe(false);
    await setWelcomeSeen();
    expect(await getWelcomeSeen()).toBe(true);
  });
});

describe("بصمة الجهاز", () => {
  it("تُولَّد مرة واحدة وتبقى", async () => {
    const first = await ensureDeviceId();
    const second = await ensureDeviceId();

    expect(first).toBe(second);
    expect(first.length).toBeGreaterThanOrEqual(16);
  });

  it("اسم الجهاز يصف المنصّة ولا يحمل هوية", () => {
    expect(describePlatform("Mozilla/5.0 (Windows NT 10.0)")).toBe("جهاز ويندوز");
    expect(describePlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X)")).toBe(
      "جهاز ماك",
    );
    expect(describePlatform("Mozilla/5.0 (X11; Linux x86_64)")).toBe("جهاز لينكس");
    expect(describePlatform("")).toBe("جهاز غير معروف");
  });

  it("اسم الجهاز يُحفظ فلا يتغيّر بين الجلسات", async () => {
    const first = await ensureDeviceName();
    expect(await ensureDeviceName()).toBe(first);
  });
});
