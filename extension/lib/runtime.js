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
  RUNTIME_DISCOVERY_TIMEOUT_MS,
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

/**
 * **رفض التفعيل** — وصل رمز التركيب إلى الـRuntime ورُدّ عليه بالرفض.
 *
 * ⚠️ **غير :class:`HandoverFailedError`.** هنا وصل الرمز وسُلّم إلى الخادم
 * ورُفض — اشتراك لا يسمح، أو جهاز آخر مفعّل — والإجراء تجديدُ اشتراك أو
 * استبدالُ جهاز. هناك لم يصل الرمز أصلًا، والإجراء إكمالُ التثبيت.
 * خلطُ الحالتين يعطي المستخدم إجراءً لا يحلّ مشكلته.
 */
export class ActivationFailedError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ActivationFailedError";
    /** رمز حالة رد الـRuntime، أو صفر إن لم يصل رد. */
    this.status = status;
  }
}

/** **تعذّر التسليم** — لم يصل رمز التركيب إلى الـRuntime أصلًا. */
export class HandoverFailedError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "HandoverFailedError";
    this.status = status;
  }
}

/**
 * رموز حالة تعني «لم يصل الرمز إلى وجهته» لا «رُفض».
 *
 * `502` يردّها الـRuntime حين يتعذّر عليه الوصول إلى خدمة GovMind،
 * و`500` حين يتعذّر عليه حفظ ربط الجهاز على القرص. كلاهما عطلٌ في الطريق
 * لا حكمٌ على الاشتراك.
 */
const TRANSPORT_STATUSES = new Set([500, 502, 503, 504]);

/**
 * يجرّب منفذًا واحدًا. يعيد الحالة أو `null` إن لم يستجب.
 *
 * ``signal`` مهلة الاكتشاف الجماعية: قطعُها يقطع كل المنافذ معًا، فلا
 * يطيل منفذٌ بطيء عمرَ الفحص كله.
 */
async function probe(port, signal, budgetMs = RUNTIME_PROBE_TIMEOUT_MS) {
  const controller = new AbortController();
  // ⚠️ **المهلة الجماعية تغلب دائمًا.** مهلة المنفذ الواحد كانت ١٥٠٠ms
  // بينما سقف الاكتشاف ١٠٠٠ms، فكان منفذٌ صامت يتجاوز السقف المعلن لأن
  // مؤقّته هو من يقطعه. الحدّ الأدنى بينهما يجعل السقف صادقًا.
  const timer = setTimeout(
    () => controller.abort(),
    Math.min(RUNTIME_PROBE_TIMEOUT_MS, budgetMs),
  );
  const relay = () => controller.abort();
  signal?.addEventListener("abort", relay, { once: true });

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
    signal?.removeEventListener("abort", relay);
  }
}

/**
 * يبحث عن الـRuntime **في كل المنافذ معًا** تحت مهلة واحدة.
 *
 * ⚠️ **كان التتابع يكلّف سبع ثوانٍ ونصفًا قبل أول رسم.** خمسة منافذ لا
 * يردّ أيٌّ منها — وهي حال كل جهاز قبل التثبيت — كانت تُنتظر واحدًا بعد
 * واحد. الآن تُطلق كلها في اللحظة نفسها، ويقطعها سقفٌ واحد.
 *
 * وترتيب الأفضلية محفوظ: يُختار أول منفذ **في ترتيب `RUNTIME_PORTS`** ممّن
 * ردّ، لا أسرعهم ردًّا، فتبقى النتيجة ثابتة لا تتبع تقلّب الشبكة.
 *
 * @returns {Promise<{port: number, health: object}|null>} و`null` تعني
 *   «لا Runtime بعد» — وهي **الحالة الطبيعية لأول تثبيت لا خطأ**.
 */
export async function findRuntime({
  timeoutMs = RUNTIME_DISCOVERY_TIMEOUT_MS,
} = {}) {
  const deadline = new AbortController();
  const timer = setTimeout(() => deadline.abort(), timeoutMs);

  try {
    const results = await Promise.all(
      RUNTIME_PORTS.map((port) => probe(port, deadline.signal, timeoutMs)),
    );
    return results.find(Boolean) ?? null;
  } finally {
    clearTimeout(timer);
  }
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
 * **الرمز يمرّ في جسم الطلب إلى `127.0.0.1` وحده.** الـRuntime يستبدله عند
 * الـBackend فيستلم **بيان اعتماد الجهاز** ويحفظه بـDPAPI.
 *
 * ⚠️ **الإضافة لا ترى بيان الاعتماد ولا تحتاجه ولا يعود في هذا الرد.** ما
 * يعود لقطةُ حالة: مرحلةٌ ورسالتها. لو عاد البيان هنا لصار في متناول كل
 * شيفرة تعمل في المتصفح، ولبطل معنى حفظه بـDPAPI أصلًا.
 *
 * @throws {ActivationFailedError} رُفض التفعيل — رسالة الخادم كما وردت.
 * @throws {HandoverFailedError} لم يصل الرمز إلى وجهته.
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
    // لم يُفتح اتصال أصلًا: الـRuntime توقّف بين الاكتشاف والتسليم.
    throw new HandoverFailedError(
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
    const detail = (body?.detail ?? "").trim();
    if (TRANSPORT_STATUSES.has(response.status)) {
      // ⚠️ **عطلٌ في الطريق لا رفضٌ للاشتراك.** رسالة الـRuntime تشرح
      // السبب (لا شبكة، أو تعذّر حفظ الربط)، والإجراء إكمال التثبيت أو
      // إعادة المحاولة — لا استبدال جهاز ولا تجديد اشتراك.
      throw new HandoverFailedError(
        detail || "تعذّر إكمال ربط هذا الجهاز. أعد المحاولة.",
        response.status,
      );
    }
    throw new ActivationFailedError(
      detail || "تعذّر تفعيل هذا الجهاز. أعد المحاولة من البداية.",
      response.status,
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
