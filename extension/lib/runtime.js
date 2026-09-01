/**
 * اكتشاف GovMind Runtime على هذا الجهاز، وتسليمه رمز التركيب.
 *
 * **لماذا استطلاع منافذ لا منفذ واحد؟** الـRuntime يفضّل منفذًا معلومًا،
 * وينتقل إلى ما بعده إن وجده مشغولًا ببرنامج آخر. الإضافة تجرّب القائمة
 * نفسها بالترتيب نفسه، فلا يحتاج المستخدم أن يعرف رقمًا ولا أن يدخله.
 *
 * ⚠️ **لا يُعرض المنفذ ولا العنوان للمستخدم في أي شاشة.** تفصيل داخلي.
 *
 * ⚠️ **رمز التركيب يُرسل مرة واحدة ثم يُمحى** — انظر `storage.clearInstallToken`.
 * وهو لا يظهر في أي رسالة خطأ ولا يُكتب في أي سجل.
 */

import {
  RUNTIME_POLL_MS,
  RUNTIME_PORTS,
  RUNTIME_PROBE_TIMEOUT_MS,
} from "../config.js";

/** حالة الـRuntime كما يعيدها `/health`. */
export class RuntimeUnavailableError extends Error {
  constructor() {
    super("لم يُعثر على GovMind على هذا الجهاز بعد.");
    this.name = "RuntimeUnavailableError";
  }
}

/** فشل تسليم رمز التركيب إلى الـRuntime. */
export class ActivationFailedError extends Error {
  constructor(message) {
    super(message);
    this.name = "ActivationFailedError";
  }
}

/** يجرّب منفذًا واحدًا. يعيد الحالة أو `null` إن لم يستجب. */
async function probe(port) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), RUNTIME_PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/health`, {
      signal: controller.signal,
    });
    if (!response.ok) return null;
    const body = await response.json();
    // منفذ قد يشغله برنامج آخر يردّ ٢٠٠ على أي مسار — التوقيع يميّزنا.
    if (body?.service !== "govmind-runtime") return null;
    return { port, health: body };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * يبحث عن الـRuntime مرة واحدة عبر كل المنافذ.
 *
 * @returns {Promise<{port: number, health: object}|null>}
 */
export async function findRuntime() {
  for (const port of RUNTIME_PORTS) {
    const found = await probe(port);
    if (found) return found;
  }
  return null;
}

/**
 * ينتظر ظهور الـRuntime حتى مهلة، مستدعيًا `onTick` عند كل محاولة.
 *
 * @param {object} options
 * @param {number} options.timeoutMs أقصى انتظار.
 * @param {() => boolean} [options.shouldStop] يوقف الانتظار إن أعادت true.
 * @param {(elapsedMs: number) => void} [options.onTick]
 */
export async function waitForRuntime({ timeoutMs, shouldStop, onTick } = {}) {
  const startedAt = Date.now();

  for (;;) {
    if (shouldStop?.()) return null;

    const found = await findRuntime();
    if (found) return found;

    const elapsed = Date.now() - startedAt;
    if (elapsed >= timeoutMs) return null;
    onTick?.(elapsed);

    await new Promise((resolve) => setTimeout(resolve, RUNTIME_POLL_MS));
  }
}

/**
 * يسلّم رمز التركيب إلى الـRuntime ليفعّل الجهاز.
 *
 * **الرمز يمرّ في جسم الطلب إلى `127.0.0.1` وحده.** الـRuntime يولّد سرّ
 * جهازه بنفسه ويستبدل الرمز بتفعيل عند الـBackend؛ الإضافة لا ترى سرّ
 * الجهاز ولا تحتاجه.
 *
 * @throws {ActivationFailedError} برسالة عربية من الـRuntime.
 */
export async function handOverToken(port, token) {
  let response;
  try {
    response = await fetch(`http://127.0.0.1:${port}/activate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
  } catch {
    throw new ActivationFailedError(
      "تعذّر الاتصال بـGovMind على هذا الجهاز. تأكد من اكتمال التثبيت.",
    );
  }

  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    throw new ActivationFailedError(
      (body?.detail ?? "").trim() ||
        "تعذّر تفعيل هذا الجهاز. أعد المحاولة من البداية.",
    );
  }
  return body ?? {};
}

/** يقرأ حالة الـRuntime بعد التفعيل — لعرض التقدّم. */
export async function readStatus(port) {
  const found = await probe(port);
  if (!found) throw new RuntimeUnavailableError();
  return found.health;
}

/** يفتح واجهة GovMind في تبويب جديد. **لا يكتب المستخدم عنوانًا.** */
export async function openGovMind(port) {
  await chrome.tabs.create({ url: `http://127.0.0.1:${port}/` });
}
