/**
 * عامل الخدمة: **تنظيف المخزن القديم عند التفعيل**.
 *
 * هذا يحرس عطلًا حيًّا. عاملُ خدمة قديم بقي مسجَّلًا على أصل الـRuntime
 * (`127.0.0.1:8765`) ظلّ يخدم هيكلًا يحمل `/login/`، فرأى المستخدم **نموذج
 * دخول ثانٍ** بعد أن ألغاه بناء سطح المكتب. والأصل واحد لكل من يحدّث من نسخة
 * أقدم، فالعطل يصيبهم جميعًا ما لم يُحذف المخزن القديم.
 *
 * ما يثبته هذا الملف: أن اسم المخزن تغيّر فعلًا، وأن `activate` يحذف القديم
 * ويبقي الحالي — لا أكثر.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";

const SW_SOURCE = readFileSync(join(process.cwd(), "public", "sw.js"), "utf8");

/** يشغّل `sw.js` في نطاق مزيّف ويعيد المستمعين ومخازن الكاش. */
function loadServiceWorker(existingCaches: string[]) {
  const deleted: string[] = [];
  const listeners = new Map<string, (event: unknown) => void>();

  const caches = {
    keys: vi.fn(async () => [...existingCaches]),
    open: vi.fn(async () => ({ addAll: vi.fn(async () => undefined) })),
    delete: vi.fn(async (name: string) => {
      deleted.push(name);
      return true;
    }),
    match: vi.fn(async () => undefined),
  };

  const self = {
    addEventListener: (type: string, handler: (event: unknown) => void) => {
      listeners.set(type, handler);
    },
    skipWaiting: vi.fn(),
    clients: { claim: vi.fn() },
    location: { origin: "http://127.0.0.1:8765" },
  };

  // eslint-disable-next-line @typescript-eslint/no-implied-eval
  new Function("self", "caches", SW_SOURCE)(self, caches);
  return { listeners, deleted, self, caches };
}

/** ينفّذ مستمعًا وينتظر ما مرّره إلى `waitUntil`. */
async function fire(
  listeners: Map<string, (event: unknown) => void>,
  type: string,
) {
  const pending: Promise<unknown>[] = [];
  listeners.get(type)?.({ waitUntil: (p: Promise<unknown>) => pending.push(p) });
  await Promise.all(pending);
}

describe("عامل الخدمة: تنظيف المخزن القديم", () => {
  let currentName: string;
  let legacyNames: string[];

  beforeAll(() => {
    currentName = /const CACHE_NAME = "([^"]+)"/.exec(SW_SOURCE)![1];
    legacyNames = JSON.parse(
      /const LEGACY_CACHES = (\[[^\]]*\])/.exec(SW_SOURCE)![1].replace(/'/g, '"'),
    );
  });

  it("⚠️ اسم المخزن لم يعد govagent-shell-v1", () => {
    // بقاءُ الاسم يعني أن `activate` لا يجد شيئًا ليحذفه، فينجو الهيكل القديم
    // من النشر — وهو العطل نفسه.
    expect(currentName).not.toBe("govagent-shell-v1");
  });

  it("⚠️ الاسم الحالي ليس في قائمة القدامى", () => {
    // لو كان فيها، لحذف التفعيلُ المخزنَ الحيّ عند كل إقلاع.
    expect(legacyNames).not.toContain(currentName);
  });

  it("govagent-shell-v1 مذكور صراحةً بين المخازن القديمة", () => {
    expect(legacyNames).toContain("govagent-shell-v1");
  });

  it("التفعيل يحذف govagent-shell-v1 ويبقي الحالي", async () => {
    const { listeners, deleted } = loadServiceWorker([
      "govagent-shell-v1",
      currentName,
    ]);

    await fire(listeners, "activate");

    expect(deleted).toContain("govagent-shell-v1");
    expect(deleted).not.toContain(currentName);
  });

  it("التفعيل يحذف أي مخزن غريب كذلك", async () => {
    const { listeners, deleted } = loadServiceWorker([
      "govagent-shell-v0",
      "govagent-shell-v1",
      currentName,
    ]);

    await fire(listeners, "activate");

    expect(deleted.sort()).toEqual(["govagent-shell-v0", "govagent-shell-v1"]);
  });

  it("التفعيل بلا مخازن قديمة لا يحذف شيئًا", async () => {
    const { listeners, deleted } = loadServiceWorker([currentName]);

    await fire(listeners, "activate");

    expect(deleted).toEqual([]);
  });

  it("⚠️ التبويبات المفتوحة تتبع العامل الجديد فورًا", async () => {
    // بلا `claim()` يبقى من فتح التطبيق قبل النشر على الهيكل القديم حتى يغلق
    // كل تبويباته — أي أن العطل يستمر عند من يعمل بلا إغلاق.
    const { listeners, self } = loadServiceWorker(["govagent-shell-v1"]);

    await fire(listeners, "activate");

    expect(self.clients.claim).toHaveBeenCalled();
  });

  it("التثبيت لا ينتظر إغلاق التبويبات", async () => {
    const { listeners, self } = loadServiceWorker([]);

    await fire(listeners, "install");

    expect(self.skipWaiting).toHaveBeenCalled();
  });
});
