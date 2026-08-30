/**
 * ترجمة كل فشل إلى رسالة عربية واحدة **وإجراء مقترح**.
 *
 * الرسالة وحدها لا تكفي: موظف يقرأ «انتهت جلستك» يحتاج زر دخول أمامه، ومن
 * يقرأ «لم يُمنح الإذن» يحتاج زر منح. لذلك يعيد كل فرع هنا `action` تبني
 * عليه النافذة الزرّ المناسب.
 *
 * الرسائل التي يكتبها الـBackend بالعربية أصلًا **تُعرض كما وردت**: فيها ما
 * لا تعرفه الإضافة، كتاريخ انتهاء الاشتراك في رسالة 403.
 */

import { ApiError, HostPermissionError, NetworkError } from "./api.js";

/**
 * @typedef {"retry"|"settings"|"signin"|"permission"|"none"} FailureAction
 * - `retry` — الفشل عابر، يعيد المحاولة.
 * - `settings` — لم يصل الطلب، يضبط رابط السيرفر.
 * - `signin` — الجلسة انتهت، يسجّل الدخول من جديد.
 * - `permission` — يمنح الإضافة إذن الاتصال بالنطاق.
 * - `none` — لا إجراء يفيده (اشتراك منتهٍ، صلاحية ناقصة).
 */

/**
 * @typedef {object} Failure
 * @property {string} message نص عربي صالح للعرض مباشرة.
 * @property {FailureAction} action
 * @property {boolean} sessionLost هل سقطت الجلسة فعلًا؟
 */

/** @returns {Failure} */
export function describeFailure(caught, fallback = "حدث خطأ غير متوقع.") {
  if (caught instanceof HostPermissionError) {
    return {
      message:
        `${caught.message} امنح الإذن للمتابعة، أو غيّر الرابط من الإعدادات.`,
      action: "permission",
      sessionLost: false,
    };
  }

  if (caught instanceof NetworkError) {
    return { message: caught.message, action: "settings", sessionLost: false };
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
        // اشتراك الجهة منتهٍ، أو الحساب معطّل، أو صلاحية ناقصة. رسالة
        // الـBackend تذكر السبب وتاريخ الانتهاء، فلا تُستبدل بعبارة عامة.
        return { message: caught.message, action: "none", sessionLost: false };
      case 404:
        return { message: caught.message, action: "retry", sessionLost: false };
      case 409:
      case 413:
      case 415:
      case 422:
        return { message: caught.message, action: "none", sessionLost: false };
      case 429:
        return {
          message: "تجاوزت عدد الطلبات المسموح. حاول بعد قليل.",
          action: "retry",
          sessionLost: false,
        };
      case 503:
        return {
          message:
            "مزود المودل غير متاح حاليًا على سيرفر جهتك. حاول بعد قليل، " +
            "وإن تكرر فراجع مسؤول النظام في جهتك.",
          action: "retry",
          sessionLost: false,
        };
      default:
        if (caught.status >= 500) {
          return {
            message:
              "حدث خطأ في خدمة جهتك. حاول مرة أخرى، وإن تكرر فراجع مسؤول النظام.",
            action: "retry",
            sessionLost: false,
          };
        }
        return { message: caught.message, action: "retry", sessionLost: false };
    }
  }

  return { message: fallback, action: "retry", sessionLost: false };
}

/** نصّ الزر المرافق لكل إجراء، أو `null` إن لم يكن هناك زر. */
export function actionLabel(action) {
  switch (action) {
    case "retry":
      return "أعد المحاولة";
    case "settings":
      return "افتح الإعدادات";
    case "signin":
      return "تسجيل الدخول";
    case "permission":
      return "امنح الإذن";
    default:
      return null;
  }
}
