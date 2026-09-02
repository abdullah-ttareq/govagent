/**
 * بصمة هذا الجهاز — تُولَّد مرة واحدة وتبقى.
 *
 * **بصمة عشوائية مخزَّنة، لا «بصمة» مستنتَجة من خصائص المتصفح.**
 * الاستنتاج من `userAgent` ودقّة الشاشة والخطوط أسلوب تتبّع، وهو في هذا
 * السياق أسوأ وظيفيًا كذلك: يتغيّر مع كل تحديث للمتصفح أو تبديل شاشة،
 * فيفقد المستخدم تفعيله بلا سبب مفهوم. معرّف عشوائي مخزَّن يبقى ثابتًا
 * ما دامت الإضافة مثبّتة، ولا يحمل عن الجهاز شيئًا.
 *
 * ⚠️ القيمة تُرسل إلى الـBackend مرة واحدة في كل عملية، **ويجزّئها هناك**
 * قبل التخزين — لا تُخزَّن خامًا في القاعدة أبدًا. انظر
 * `backend/app/core/device_id.py`.
 *
 * **حدّه المعروف:** إعادة تثبيت الإضافة أو استخدام ملف تعريف Chrome آخر
 * يولّد معرّفًا جديدًا على الجهاز نفسه، فيحتاج المستخدم إلى استبدال الجهاز.
 * هذا مقبول في هذه المرحلة: الربط الحقيقي بعتاد الجهاز يأتي مع GovMind
 * Runtime في المرحلة التالية، وهو الذي يملك الوصول إلى معرّفات النظام.
 */

import { getDeviceId, getDeviceName, setDeviceId, setDeviceName } from "./storage.js";

/** يولّد معرّفًا عشوائيًا بـ`crypto`، لا بـ`Math.random`. */
function generateDeviceId() {
  if (typeof crypto?.randomUUID === "function") return crypto.randomUUID();

  // بديل لبيئات لا تعرّف `randomUUID` (اختبارات، متصفحات قديمة).
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * اسم وصفي للجهاز يميّزه لصاحب الحساب.
 *
 * يُشتقّ من نظام التشغيل وحده — لا يحمل اسم المستخدم ولا أي معرّف. صاحب الحساب
 * يحتاج أن يميّز «حاسب ويندوز» عن «حاسب ماك» لا أن يعرف من يجلس أمامه.
 */
export function describePlatform(userAgent = navigator.userAgent) {
  const agent = String(userAgent || "");
  if (/Windows/i.test(agent)) return "جهاز ويندوز";
  if (/Macintosh|Mac OS/i.test(agent)) return "جهاز ماك";
  if (/Linux/i.test(agent)) return "جهاز لينكس";
  return "جهاز غير معروف";
}

/**
 * يعيد بصمة هذا الجهاز، ويولّدها ويحفظها عند أول استدعاء.
 *
 * **مُعادة التنفيذ:** الاستدعاء مرارًا يعيد القيمة نفسها دائمًا.
 */
export async function ensureDeviceId() {
  const existing = await getDeviceId();
  if (existing) return existing;

  const generated = generateDeviceId();
  await setDeviceId(generated);
  return generated;
}

/** يعيد اسم الجهاز المحفوظ، ويشتقّه من المنصّة عند أول استدعاء. */
export async function ensureDeviceName() {
  const existing = await getDeviceName();
  if (existing) return existing;

  const derived = describePlatform();
  await setDeviceName(derived);
  return derived;
}
