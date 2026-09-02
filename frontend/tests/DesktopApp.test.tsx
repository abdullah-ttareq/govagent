/**
 * تطبيق GovMind المثبَّت: **بلا دخول ثانٍ، وبلا لفظ من المنتج القديم**.
 *
 * ⚠️ **العطل الحيّ الذي تحرسه هذه الاختبارات.** بعد أن اكتمل التثبيت وفتح
 * العميل GovMind، ظهر له نموذج دخول ثانٍ — وقد سجّل دخوله في الإضافة قبل
 * دقائق — وإرسالُه ردّ بـ«Method Not Allowed».
 *
 * ما تثبته:
 *
 * ١) لا نموذج دخول في التطبيق المثبَّت، مهما كانت حالة الربط.
 * ٢) قبل اكتمال الربط: تعليمة الإضافة وزرّ «إعادة التحقق» — لا خطأ HTTP.
 * ٣) بعد اكتماله: التطبيق مباشرة.
 * ٤) لا عنوان خدمة مكتوب في شيفرة المتصفح، ولا بيان اعتماد يصلها.
 * ٥) لا لفظ «جهة» ولا «مسؤول» ولا «بريد عمل» في حزمة العميل.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DesktopApp from "@/components/desktop/DesktopApp";

const SESSION_TOKEN = "local-session-token-for-tests";

/** لقطة حالة كما يعيدها `GET /api/app/session` من الـRuntime. */
function session(overrides: Record<string, unknown> = {}) {
  return {
    service: "govmind-runtime",
    linked: true,
    phase: "ready",
    message: "GovMind جاهز للاستخدام.",
    progress: null,
    downloaded_bytes: 0,
    total_bytes: 0,
    device_name: "حاسب ويندوز 11",
    subscription_status: "trial",
    subscription_expires_at: "2027-01-01T00:00:00+00:00",
    account_email: "owner@example.test",
    is_ready: true,
    needs_activation: false,
    ...overrides,
  };
}

/**
 * موجّه طلبات مزيّف — **يرفض أي عنوان مطلق**.
 *
 * ⚠️ هذا جوهر الاختبار لا تفصيلًا فيه: الصفحة تُخدَم من الـRuntime، وأي
 * عنوان مكتوب في شيفرة المتصفح يضع خدمةً بعيدة في متناول كل سكربت.
 */
function routeFetch(routes: Record<string, unknown>) {
  return vi.fn(async (url: RequestInfo | URL, options: RequestInit = {}) => {
    const path = String(url);
    if (/^https?:\/\//.test(path)) {
      throw new Error(`عنوان مطلق في شيفرة المتصفح: ${path}`);
    }

    const key = `${options.method ?? "GET"} ${path}`;
    const body = routes[key] ?? routes[path];
    if (body === undefined) throw new Error(`مسار غير متوقّع: ${key}`);
    if (body instanceof Error) throw body;

    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
}

function mount(routes: Record<string, unknown>) {
  const fetchMock = routeFetch({
    "/api/local/session": { token: SESSION_TOKEN },
    ...routes,
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<DesktopApp />);
  return fetchMock;
}

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/* ======================================================================== */
describe("لا تسجيل دخول ثانٍ في التطبيق المثبَّت", () => {
  it("لا يعرض أي حقل بريد أو كلمة مرور، ولو لم يكتمل الربط", async () => {
    mount({ "/api/app/session": session({ linked: false, is_ready: false }) });

    await screen.findByText("أكمل تثبيت وربط GovMind من إضافة المتصفح.");

    // ⚠️ **الفحص على ما يستطيع المستخدم إدخاله**، لا على ورود كلمة
    // «دخول» في نصّ. الشاشة تقول صراحةً «لا حاجة إلى تسجيل الدخول هنا»،
    // وهي جملة مطلوبة: العميل جاء يبحث عن نموذج فلا يجده.
    expect(document.querySelector("form")).toBeNull();
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(document.querySelector('input[type="email"]')).toBeNull();
    expect(document.querySelector('input[name="email"]')).toBeNull();
    expect(screen.queryByRole("button", { name: /^(تسجيل الدخول|دخول)$/ })).toBeNull();
  });

  it("⚠️ لا يعرض «Method Not Allowed» في أي حالة", async () => {
    mount({ "/api/app/session": session({ linked: false, is_ready: false }) });
    await screen.findByRole("button", { name: "إعادة التحقق" });

    expect(document.body.textContent).not.toContain("Method Not Allowed");
    expect(document.body.textContent).not.toContain("405");
  });

  it("يعطي «إعادة التحقق» ويستدعي مسار الفحص عند الضغط", async () => {
    const fetchMock = mount({
      "/api/app/session": session({ linked: false, is_ready: false }),
      "POST /api/app/recheck": session(),
    });

    const button = await screen.findByRole("button", { name: "إعادة التحقق" });
    fireEvent.click(button);

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, options]) =>
            String(url) === "/api/app/recheck" &&
            (options as RequestInit | undefined)?.method === "POST",
        ),
      ).toBe(true),
    );
  });

  it("الربط الناجح يفتح التطبيق مباشرة", async () => {
    mount({ "/api/app/session": session() });

    await screen.findByPlaceholderText("اكتب سؤالك…");
    expect(screen.getByRole("button", { name: "إرسال" })).toBeTruthy();
    expect(document.body.textContent).not.toContain("أكمل تثبيت وربط GovMind");
  });

  it("يعرض بريد الحساب المربوط بلا أن يطلبه", async () => {
    mount({ "/api/app/session": session() });
    await screen.findByText("owner@example.test");
  });
});

describe("حالات التجهيز والمنع", () => {
  it("أثناء التجهيز يعرض رسالة الـRuntime وتقدّمه", async () => {
    mount({
      "/api/app/session": session({
        is_ready: false,
        phase: "downloading_model",
        message: "جارٍ تنزيل المودل…",
        progress: 42,
        downloaded_bytes: 42 * 1024 * 1024,
        total_bytes: 100 * 1024 * 1024,
      }),
    });

    await screen.findByText("جارٍ تنزيل المودل…");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "42",
    );
  });

  it("الاشتراك المانع يعرض سبب السيرفر لا خطأً عامًا", async () => {
    mount({
      "/api/app/session": session({
        is_ready: false,
        phase: "blocked",
        message: "انتهى اشتراكك بتاريخ ٢٠٢٦-٠١-٠١. جدّد اشتراكك للمتابعة.",
      }),
      "POST /api/app/recheck": session(),
    });

    await screen.findByText(
      "انتهى اشتراكك بتاريخ ٢٠٢٦-٠١-٠١. جدّد اشتراكك للمتابعة.",
    );
    expect(screen.getByRole("button", { name: "إعادة التحقق" })).toBeTruthy();
  });

  it("توقّف الـRuntime يعطي رسالة عربية لا شاشة بيضاء", async () => {
    mount({ "/api/app/session": new Error("Failed to fetch") });

    await screen.findByText(/تعذّر الاتصال بخدمة GovMind على هذا الجهاز/);
  });
});

/* ======================================================================== */
describe("⚠️ حدود ما يصل المتصفح", () => {
  /**
   * يزيل التعليقات قبل الفحص.
   *
   * ⚠️ **ضروري لأي فحص «لا يوجد كذا في الشيفرة».** توثيقُ ما لا نفعله —
   * ولماذا لا نفعله — يذكر أسماءه بالضرورة (`127.0.0.1:8000`،
   * `RequireAuth`)، وفحصُ نصّ الملف كاملًا يحوّل كل شرح أمني إلى مخالفة،
   * فيدفع إلى حذف الشروح بدل حذف السلوك.
   */
  function stripComments(source: string): string {
    return source
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .split(/\r?\n/)
      .map((line) => line.replace(/(^|\s)\/\/.*$/, ""))
      .join("\n");
  }

  const CLIENT_SOURCES = [
    "components/desktop/DesktopApp.tsx",
    "lib/runtime-client.ts",
    "app/page.desktop.tsx",
    "app/layout.desktop.tsx",
  ].map((path) => ({
    path,
    source: stripComments(readFileSync(resolve(process.cwd(), path), "utf-8")),
  }));

  it("لا عنوان خدمة مكتوب في أي ملف من ملفات التطبيق المثبَّت", () => {
    // ⚠️ **هذا ما يمنع «الإصلاح» الخاطئ.** كتابة `127.0.0.1:8000` في
    // شيفرة المتصفح تجعل الصفحة تنادي الـControl Plane مباشرة، فيبطل
    // معنى بيان اعتماد الجهاز كله: الوسيط الذي يحمله هو الـRuntime.
    for (const { path, source } of CLIENT_SOURCES) {
      expect(source, path).not.toContain("127.0.0.1:8000");
      expect(source, path).not.toContain("localhost:8000");
      expect(source, path).not.toMatch(/https?:\/\/[^\s"']*supabase/);
      expect(source, path).not.toContain("blob.core.windows.net");
    }
  });

  it("لا يطلب أي ملف بيان اعتماد الجهاز ولا يخزّنه", () => {
    for (const { path, source } of CLIENT_SOURCES) {
      expect(source, path).not.toContain("device_credential");
      expect(source, path).not.toContain("X-GovMind-Device-Credential");
    }
  });

  it("⚠️ لا لفظ من المنتج القديم في حزمة العميل", () => {
    for (const { path, source } of CLIENT_SOURCES) {
      for (const word of ["مسؤول النظام", "مسؤول الجهة", "جهتك", "بريد العمل"]) {
        expect(source, `${path} يذكر «${word}»`).not.toContain(word);
      }
    }
  });

  it("لا يستورد التطبيق المثبَّت طبقة الدخول ولا لوحة الإدارة", () => {
    // الاستيراد وحده يُدخل نصوصها الحزمةَ المصدَّرة، ولو لم تُعرض شاشة.
    for (const { path, source } of CLIENT_SOURCES) {
      expect(source, path).not.toContain("AuthProvider");
      expect(source, path).not.toContain("@/lib/auth");
      expect(source, path).not.toContain("RequireAuth");
      expect(source, path).not.toContain("RequireAdmin");
      expect(source, path).not.toContain("Workspace");
    }
  });

  it("⚠️ بناء سطح المكتب لا يبني صفحة دخول أصلًا", () => {
    // شرطٌ في الشيفرة يخفي الصفحة ويُبقي نصّها في الحزمة. `pageExtensions`
    // يجعلها **غير مبنيّة**، فيصير الشرط قابلًا للفحص لا وعدًا.
    const config = readFileSync(resolve(process.cwd(), "next.config.ts"), "utf-8");
    expect(config).toContain('pageExtensions: ["desktop.tsx"]');
    expect(config).toContain('output: "export"');
  });
});
