/**
 * ترجمة كل فشل إلى رسالة عربية واحدة **وإجراء مقترح**.
 *
 * الرسالة وحدها لا تكفي: من يقرأ «انتهت جلستك» يحتاج زر دخول أمامه، ومن
 * يقرأ «مفعّل على جهاز آخر» لا يحتاج زرًّا إطلاقًا لأن الحل عند مسؤوله.
 * لذلك يعيد كل فرع هنا `action` تبني عليه النافذة الزرّ المناسب.
 *
 * الرسائل التي يكتبها الـBackend بالعربية أصلًا **تُعرض كما وردت**: فيها ما
 * لا تعرفه الإضافة، كتاريخ انتهاء الاشتراك واسم الجهاز المفعّل.
 *
 * ⚠️ **زال إجراء `settings` وإجراء `permission`.** الأول كان يفتح شاشة
 * رابط السيرفر، والثاني يطلب إذن نطاق يختاره المستخدم — وكلاهما اختفى مع
 * تثبيت العنوان وقت البناء. لا يُعادان.
 */

import { ApiError, NetworkError } from "./api.js";

/**
 * @typedef {"retry"|"signin"|"none"} FailureAction
 * - `retry` — الفشل عابر، يعيد المحاولة.
 * - `signin` — الجلسة انتهت، يسجّل الدخول من جديد.
 * - `none` — لا إجراء يفيده (اشتراك منتهٍ، جهاز آخر، حساب بلا جهة).
 */

/**
 * @typedef {object} Failure
 * @property {string} message نص عربي صالح للعرض مباشرة.
 * @property {FailureAction} action
 * @property {boolean} sessionLost هل سقطت الجلسة فعلًا؟
 */

/** @returns {Failure} */
export function describeFailure(caught, fallback = "حدث خطأ غير متوقع.") {
  if (caught instanceof NetworkError) {
    return { message: caught.message, action: "retry", sessionLost: false };
  }

  if (caught instanceof ApiError) {
    switch (caught.status) {
      case 401:
        return {
          message: "انتهت جلستك. سجّل الدخول من جديد للمتابعة.",
          action: "signin",
          sessionLost: true,
        };
      case 403:
        // اشتراك منتهٍ أو موقوف، أو حساب بلا جهة، أو صلاحية ناقصة. رسالة
        // الـBackend تذكر السبب وتاريخ الانتهاء، فلا تُستبدل بعبارة عامة.
        return { message: caught.message, action: "none", sessionLost: false };
      case 409:
        // مفعّل على جهاز آخر، أو لا جهاز مفعّلًا. الحل عند المسؤول لا هنا.
        return { message: caught.message, action: "none", sessionLost: false };
      case 400:
      case 404:
      case 422:
        return { message: caught.message, action: "retry", sessionLost: false };
      case 429:
        return {
          message: "محاولات كثيرة خلال وقت قصير. انتظر قليلًا ثم أعد المحاولة.",
          action: "retry",
          sessionLost: false,
        };
      case 503:
        // إعداد ناقص على السيرفر أو خدمة لا تستجيب — رسالة السيرفر تسمّي
        // المتغيّر الناقص، وهي ما يحتاجه مسؤول النظام حرفيًا.
        return { message: caught.message, action: "retry", sessionLost: false };
      default:
        if (caught.status >= 500) {
          return {
            message:
              "حدث خطأ في خدمة GovMind. حاول مرة أخرى، وإن تكرر فراجع مسؤول النظام.",
            action: "retry",
            sessionLost: false,
          };
        }
        return { message: caught.message, action: "retry", sessionLost: false };
    }
  }

  // خطأ محلي (تنزيل رفضه المتصفح مثلًا) برسالة عربية مكتوبة عند مصدره.
  if (caught instanceof Error && caught.message) {
    return { message: caught.message, action: "retry", sessionLost: false };
  }

  return { message: fallback, action: "retry", sessionLost: false };
}

/** نصّ الزر المرافق لكل إجراء، أو `null` إن لم يكن هناك زر. */
export function actionLabel(action) {
  switch (action) {
    case "retry":
      return "أعد المحاولة";
    case "signin":
      return "تسجيل الدخول";
    default:
      return null;
  }
}
