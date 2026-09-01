/**
 * الشاشات التسع — **كل حالة تُختبر صراحة**.
 *
 * التدفّق دالة نقية في `lib/steps.js`، فيمكن تغطيته كله بلا DOM ولا شبكة.
 * هذا هو الغرض من فصله: الحالة التي لا تُختبر هي التي تُعرض للعميل خطأ.
 */

import { describe, expect, it } from "vitest";
import {
  RUNTIME_BUSY_PHASES,
  STEPS,
  STEP_NUMBERS,
  STEP_TITLES,
  TOTAL_STEPS,
  isDeviceTaken,
  resolveStep,
} from "../lib/steps.js";

const account = { email: "a@b.test", role: "employee", organization_id: 1 };

const usable = {
  status: "active",
  is_usable: true,
  blocked_reason: null,
  requires_activation: false,
  device: {
    id: 1,
    device_name: "حاسب المكتب",
    is_current_device: true,
    activated_at: "2026-01-01T00:00:00Z",
    last_seen_at: "2026-01-02T00:00:00Z",
  },
};

const signedIn = { hasSession: true, welcomeSeen: true, account };

describe("١) الترحيب والدخول", () => {
  it("يبدأ بالترحيب في أول تشغيل", () => {
    expect(resolveStep({})).toBe(STEPS.WELCOME);
  });

  it("يتخطّى الترحيب لمن رآه من قبل", () => {
    expect(resolveStep({ welcomeSeen: true })).toBe(STEPS.SIGNIN);
  });

  it("لا يعرض شيئًا بعد الدخول لمن لا جلسة له", () => {
    // حتى لو كانت بقية الحالة كاملة، غياب الجلسة يسبق كل شيء.
    expect(
      resolveStep({ welcomeSeen: true, account, subscription: usable }),
    ).toBe(STEPS.SIGNIN);
  });
});

describe("٢) حساب بلا جهة", () => {
  it("يعرض شاشة «راجع مسؤول النظام»", () => {
    expect(resolveStep({ hasSession: true, welcomeSeen: true, account: null })).toBe(
      STEPS.NOT_PROVISIONED,
    );
  });
});

describe("٣) الاشتراك", () => {
  it.each(["expired", "suspended", "cancelled"])(
    "يحجب الاستخدام عند الحالة %s",
    (status) => {
      const step = resolveStep({
        ...signedIn,
        subscription: {
          ...usable,
          status,
          is_usable: false,
          blocked_reason: "سبب من السيرفر",
        },
      });
      expect(step).toBe(STEPS.SUBSCRIPTION_BLOCKED);
    },
  );

  it("يسمح بالفترة التجريبية كالاشتراك الفعّال", () => {
    expect(
      resolveStep({ ...signedIn, subscription: { ...usable, status: "trial" } }),
    ).toBe(STEPS.INSTALL);
  });

  it("الحجب يسبق التنزيل ولو كان مكتملًا من جلسة سابقة", () => {
    // من انتهى اشتراكه لا يُعرض له «افتح المثبّت» لأن `download` باقٍ.
    const step = resolveStep({
      ...signedIn,
      subscription: { ...usable, is_usable: false },
      download: "done",
    });
    expect(step).toBe(STEPS.SUBSCRIPTION_BLOCKED);
  });

  it("لا يفترض شيئًا إن لم تصل حالة الاشتراك", () => {
    expect(resolveStep({ ...signedIn, subscription: null })).toBe(STEPS.ACTIVATE);
  });
});

describe("٤) الجهاز الواحد", () => {
  it("يعرض «مفعّل على جهاز آخر» حين يكون المفعّل غير هذا الجهاز", () => {
    const step = resolveStep({
      ...signedIn,
      subscription: {
        ...usable,
        requires_activation: true,
        device: { ...usable.device, is_current_device: false },
      },
    });
    expect(step).toBe(STEPS.DEVICE_TAKEN);
  });

  it("يعرض التفعيل حين لا جهاز مفعّلًا بعد", () => {
    const step = resolveStep({
      ...signedIn,
      subscription: { ...usable, device: null, requires_activation: true },
    });
    expect(step).toBe(STEPS.ACTIVATE);
  });

  it("غياب الجهاز ليس «جهازًا آخر أخذه»", () => {
    expect(isDeviceTaken({ device: null })).toBe(false);
    expect(isDeviceTaken({})).toBe(false);
    expect(isDeviceTaken({ device: { is_current_device: true } })).toBe(false);
    expect(isDeviceTaken({ device: { is_current_device: false } })).toBe(true);
  });

  it("شاشة «جهاز آخر» تسبق شاشة التفعيل", () => {
    // كلا الشرطين صحيح هنا؛ الأولوية للأوضح سببًا.
    const step = resolveStep({
      ...signedIn,
      subscription: {
        ...usable,
        requires_activation: true,
        device: { ...usable.device, is_current_device: false },
      },
    });
    expect(step).not.toBe(STEPS.ACTIVATE);
  });
});

describe("٥) التنزيل", () => {
  it("يعرض زر التثبيت على جهاز مفعّل واشتراك سليم", () => {
    expect(resolveStep({ ...signedIn, subscription: usable })).toBe(STEPS.INSTALL);
  });

  it("يعرض شريط التقدّم أثناء التنزيل", () => {
    expect(
      resolveStep({ ...signedIn, subscription: usable, download: "running" }),
    ).toBe(STEPS.DOWNLOADING);
  });

  it("بعد اكتمال التنزيل ينتظر فتح المثبّت", () => {
    // لا شاشة «اكتمل التنزيل» منفصلة: هذه تقول الشيء نفسه وتنتظر النتيجة.
    expect(
      resolveStep({ ...signedIn, subscription: usable, download: "done" }),
    ).toBe(STEPS.AWAITING_RUNTIME);
  });
});

describe("٦) الـRuntime بعد التثبيت", () => {
  const ready = { is_ready: true, needs_activation: false, phase: "ready" };
  const needsActivation = {
    is_ready: false,
    needs_activation: true,
    phase: "awaiting_activation",
  };
  const preparing = {
    is_ready: false,
    needs_activation: false,
    phase: "downloading_model",
  };

  it("وجود Runtime يسبق كل ما يخصّ المثبّت", () => {
    // من ثبّت البرنامج فعلًا لا يُعرض له «نزّل المثبّت» من جديد.
    expect(
      resolveStep({ ...signedIn, subscription: usable, runtime: ready }),
    ).toBe(STEPS.INSTALLED);
  });

  it("Runtime ينتظر التفعيل يعرض شاشة انتظار المثبّت", () => {
    expect(
      resolveStep({
        ...signedIn,
        subscription: usable,
        download: "done",
        runtime: needsActivation,
      }),
    ).toBe(STEPS.AWAITING_RUNTIME);
  });

  it("تسليم الرمز الجاري يعرض شاشة التفعيل", () => {
    expect(
      resolveStep({
        ...signedIn,
        subscription: usable,
        runtime: needsActivation,
        handingOver: true,
      }),
    ).toBe(STEPS.ACTIVATING_DEVICE);
  });

  it("تنزيل المودل يعرض شاشة التجهيز", () => {
    expect(
      resolveStep({ ...signedIn, subscription: usable, runtime: preparing }),
    ).toBe(STEPS.PREPARING_MODEL);
  });

  it("اشتراك محجوب يسبق حالة الـRuntime", () => {
    // Runtime جاهز على جهاز اشتراكه انتهى: الحجب هو ما يُعرض.
    expect(
      resolveStep({
        ...signedIn,
        subscription: { ...usable, is_usable: false },
        runtime: ready,
      }),
    ).toBe(STEPS.SUBSCRIPTION_BLOCKED);
  });

  it("مراحل انشغال الـRuntime تطابق ما يعلنه البرنامج", () => {
    // القائمة منسوخة من `runtime/govmind_runtime/state.py` — اختلافهما
    // يجعل الإضافة تعرض شاشة خاطئة لمرحلة صحيحة.
    expect([...RUNTIME_BUSY_PHASES]).toEqual([
      "activating",
      "downloading_model",
      "verifying_model",
      "starting_model",
    ]);
  });
});

describe("سلامة الجداول", () => {
  it("لكل شاشة عنوان", () => {
    for (const step of Object.values(STEPS)) {
      expect(STEP_TITLES[step], step).toBeTruthy();
    }
  });

  it("الشاشات المانعة بلا رقم خطوة", () => {
    // ليست خطوة في المسار، فإعطاؤها رقمًا يوهم بأن بعدها ما يبلغه المستخدم.
    expect(STEP_NUMBERS[STEPS.SUBSCRIPTION_BLOCKED]).toBeUndefined();
    expect(STEP_NUMBERS[STEPS.DEVICE_TAKEN]).toBeUndefined();
    expect(STEP_NUMBERS[STEPS.NOT_PROVISIONED]).toBeUndefined();
  });

  it("أرقام الخطوات ضمن الإجمالي المعلن", () => {
    for (const value of Object.values(STEP_NUMBERS)) {
      expect(value).toBeGreaterThanOrEqual(1);
      expect(value).toBeLessThanOrEqual(TOTAL_STEPS);
    }
  });
});
