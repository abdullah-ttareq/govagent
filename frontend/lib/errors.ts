/**
 * ترجمة كل فشل إلى رسالة عربية واحدة صالحة للعرض.
 *
 * مكانها هنا لا داخل مكوّن، لأن كل طبقة تحتاجها: الشات والمحادثات والملفات
 * وصفحة الإعدادات. **لا شاشة بيضاء ولا خطأ صامت**: كل مسار فشل ينتهي إلى
 * نصّ من هنا.
 */

import { ApiError, NetworkError } from "@/lib/api";

/** ما الذي يفعله المستخدم بعد الخطأ؟ */
export type FailureAction =
  /** يعيد المحاولة — الفشل عابر أو خارج عن المحتوى. */
  | "retry"
  /** يضبط رابط السيرفر — لم يصل الطلب أصلًا. */
  | "settings"
  /** يسجّل الدخول من جديد. */
  | "signin"
  /** لا شيء يفيد — قرار خارج يده (اشتراك منتهٍ، صلاحية ناقصة). */
  | "none";

export type Failure = {
  message: string;
  action: FailureAction;
};

/**
 * `403` حالتان مختلفتان تمامًا: اشتراك الجهة منتهٍ، أو صلاحية ناقصة على
 * إجراء بعينه. الرسالة تأتي من الـBackend في الحالتين وفيها ما لا تعرفه
 * الواجهة (تاريخ الانتهاء مثلًا)، فتُعرض كما وردت.
 */
export function describeFailureDetail(
  caught: unknown,
  fallback: string,
): Failure {
  if (caught instanceof NetworkError) {
    return { message: caught.message, action: "settings" };
  }

  if (caught instanceof ApiError) {
    switch (caught.status) {
      case 401:
        return {
          message: "انتهت جلستك. سجّل الدخول من جديد للمتابعة.",
          action: "signin",
        };
      case 403:
        return { message: caught.message, action: "none" };
      case 404:
        return { message: caught.message, action: "retry" };
      case 409:
      case 413:
      case 415:
      case 422:
        // رسائل الـBackend لهذه الحالات تشرح السبب والحل بالعربية أصلًا.
        return { message: caught.message, action: "none" };
      case 429:
        return {
          message: "تجاوزت عدد الطلبات المسموح. حاول بعد قليل.",
          action: "retry",
        };
      case 503:
        return {
          message:
            "مزود المودل غير متاح حاليًا على سيرفر جهتك. حاول بعد قليل، " +
            "وإن تكرر فراجع مسؤول النظام في جهتك.",
          action: "retry",
        };
      default:
        if (caught.status >= 500) {
          return {
            message:
              "حدث خطأ في خدمة جهتك. حاول مرة أخرى، وإن تكرر فراجع مسؤول النظام.",
            action: "retry",
          };
        }
        return { message: caught.message, action: "retry" };
    }
  }

  return { message: fallback, action: "retry" };
}

/** الصيغة النصّية وحدها، لمن لا يعرض زر إجراء. */
export function describeFailure(caught: unknown, fallback: string): string {
  return describeFailureDetail(caught, fallback).message;
}
