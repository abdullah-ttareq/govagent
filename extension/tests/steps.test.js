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
  isThisDeviceLinked,
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
      resolveStep({
        ...signedIn,
        planAcknowledged: true,
        subscription: { ...usable, status: "trial" },
      }),
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
    // فشل مغلق: يُعرض التثبيت لا التفعيل، فالإضافة لا تفعّل جهازًا أصلًا.
    expect(resolveStep({ ...signedIn, subscription: null })).toBe(STEPS.INSTALL);
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

  it("⚠️ أول جهاز يبدأ بالتثبيت لا بالتفعيل", () => {
    // **اختبار انحدار للعطل الحيّ.** كان يعيد `ACTIVATE`، فيرى صاحب أول
    // جهاز شاشةَ «تفعيل هذا الجهاز» وزرُّها يفعّل بصمة المتصفح فيشغل
    // خانةَ الجهاز الوحيدة بهوية لا يملكها الـRuntime.
    const step = resolveStep({
      ...signedIn,
      planAcknowledged: true,
      subscription: { ...usable, device: null, requires_activation: true },
    });
    expect(step).toBe(STEPS.INSTALL);
  });

  it("⚠️ `resolveStep` لا يعيد `ACTIVATE` في أي حال", () => {
    // الإضافة لا تفعّل جهازًا إطلاقًا — التفعيل من الـRuntime وحده.
    const combinations = [];
    for (const requires of [true, false]) {
      for (const plan of [true, false]) {
        for (const download of ["idle", "running", "done"]) {
          for (const started of [true, false]) {
            for (const runtime of [null, { needs_activation: true }, { is_ready: true }]) {
              combinations.push(
                resolveStep({
                  ...signedIn,
                  planAcknowledged: plan,
                  installStarted: started,
                  download,
                  runtime,
                  subscription: {
                    ...usable,
                    device: null,
                    requires_activation: requires,
                  },
                }),
              );
            }
          }
        }
      }
    }
    expect(combinations).not.toContain(STEPS.ACTIVATE);
  });

  it("غياب الجهاز ليس «جهازًا آخر أخذه»", () => {
    expect(isDeviceTaken({ device: null })).toBe(false);
    expect(isDeviceTaken({})).toBe(false);
    expect(isDeviceTaken({ device: { is_current_device: true } })).toBe(false);
    expect(isDeviceTaken({ device: { is_current_device: false } })).toBe(true);
  });

  it("شاشة «جهاز آخر» تسبق كل شاشات التثبيت", () => {
    // كلا الشرطين صحيح هنا؛ الأولوية للأوضح سببًا.
    const step = resolveStep({
      ...signedIn,
      subscription: {
        ...usable,
        requires_activation: true,
        device: { ...usable.device, is_current_device: false },
      },
    });
    expect(step).not.toBe(STEPS.INSTALL);
    expect(step).not.toBe(STEPS.CHOOSE_PLAN);
  });
});

describe("٥) التنزيل والتثبيت — بالترتيب الصحيح", () => {
  const ready = { ...signedIn, subscription: usable, planAcknowledged: true };

  it("اختيار طريقة البدء يسبق التثبيت", () => {
    expect(resolveStep({ ...signedIn, subscription: usable })).toBe(
      STEPS.CHOOSE_PLAN,
    );
  });

  it("يعرض زر التثبيت بعد إقرار طريقة البدء", () => {
    expect(resolveStep(ready)).toBe(STEPS.INSTALL);
  });

  it("يعرض شريط التقدّم أثناء التنزيل", () => {
    expect(resolveStep({ ...ready, download: "running" })).toBe(
      STEPS.DOWNLOADING,
    );
  });

  it("⚠️ بعد اكتمال التنزيل: تعليمات الفتح، **لا انتظار الـRuntime**", () => {
    // **نصف العطل الثاني.** كانت الإضافة تنتظر برنامجًا لم يُثبَّت بعد،
    // فتعرض «جارٍ البحث» والملف ما زال في مجلد التنزيلات لم يفتحه أحد.
    expect(resolveStep({ ...ready, download: "done" })).toBe(
      STEPS.INSTALLER_READY,
    );
  });

  it("الانتظار يبدأ بعد أن يعلن المستخدم أنه فتح المثبّت", () => {
    expect(
      resolveStep({ ...ready, download: "done", installStarted: true }),
    ).toBe(STEPS.AWAITING_RUNTIME);
  });

  it("⚠️ انتهاء المهلة يعطي شاشة تشخيص لا انتظارًا بلا نهاية", () => {
    expect(
      resolveStep({
        ...ready,
        download: "done",
        installStarted: true,
        runtimeTimedOut: true,
      }),
    ).toBe(STEPS.INSTALL_HELP);
  });

  it("Runtime مثبَّت يتخطّى شاشة الخطة وشاشات المثبّت", () => {
    // من ثبّت البرنامج لا يُسأل عن خطة ولا يُعرض له «نزّل المثبّت».
    expect(
      resolveStep({ ...signedIn, subscription: usable, runtime: { is_ready: true } }),
    ).toBe(STEPS.INSTALLED);
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

  const started = { planAcknowledged: true, download: "done", installStarted: true };

  it("Runtime ينتظر التفعيل يعرض شاشة انتظار المثبّت", () => {
    expect(
      resolveStep({
        ...signedIn,
        ...started,
        subscription: usable,
        runtime: needsActivation,
      }),
    ).toBe(STEPS.AWAITING_RUNTIME);
  });

  it("تسليم الرمز الجاري يعرض شاشة التفعيل", () => {
    expect(
      resolveStep({
        ...signedIn,
        ...started,
        subscription: usable,
        runtime: needsActivation,
        handingOver: true,
      }),
    ).toBe(STEPS.ACTIVATING_DEVICE);
  });

  it("تنزيل المودل يعرض شاشة التجهيز", () => {
    expect(
      resolveStep({ ...signedIn, ...started, subscription: usable, runtime: preparing }),
    ).toBe(STEPS.PREPARING_MODEL);
  });

  // ---------------------------------------------------------------------
  // ⚠️ العطل الحيّ: شاشة تفعيل تظهر عند الإقلاع بلا فعل من المستخدم
  // ---------------------------------------------------------------------
  it("⚠️ Runtime عالق في «activating» لا يعرض شاشة التفعيل عند الإقلاع", () => {
    // **ما رآه المستخدم حيًّا.** بقيّةُ تثبيتٍ سابق متعثّر تقول
    // `phase: "activating"`، فكانت النافذة تعرض «جارٍ تفعيل هذا الجهاز»
    // فور فتحها: بلا جلسة تركيب، وبلا تنزيل، وبلا أن يطلب أحدٌ شيئًا.
    const step = resolveStep({
      ...signedIn,
      planAcknowledged: true,
      subscription: usable,
      runtime: { ...needsActivation, phase: "activating" },
      installStarted: false,
    });

    expect(step).not.toBe(STEPS.ACTIVATING_DEVICE);
    expect(step).toBe(STEPS.INSTALL);
  });

  it("⚠️ ولا شاشة انتظار ولا تجهيز قبل أن يبدأ المستخدم التثبيت", () => {
    for (const runtime of [needsActivation, preparing]) {
      const step = resolveStep({
        ...signedIn,
        planAcknowledged: true,
        subscription: usable,
        runtime,
        installStarted: false,
      });
      expect([STEPS.AWAITING_RUNTIME, STEPS.PREPARING_MODEL]).not.toContain(step);
    }
  });

  it("Runtime جاهز يُعرض دائمًا، بدأ المستخدم تثبيتًا أو لم يبدأ", () => {
    // الجهوز ليس تقدّمًا يُنتظر: هو النتيجة، فلا شرط عليه.
    expect(
      resolveStep({
        ...signedIn,
        planAcknowledged: true,
        subscription: usable,
        runtime: ready,
        installStarted: false,
      }),
    ).toBe(STEPS.INSTALLED);
  });

  it("⚠️ شاشة الفحص المحايدة تسبق كل شيء أثناء الإقلاع", () => {
    const step = resolveStep({
      ...signedIn,
      subscription: usable,
      runtime: { ...needsActivation, phase: "activating" },
      booting: true,
    });

    expect(step).toBe(STEPS.CHECKING);
    expect(STEP_TITLES[step]).toBe("جاري التحقق...");
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

/* ======================================================================== */
/**
 * ترتيب ما بعد التنزيل — **الحالات التي أعطت العميل شاشة لا مخرج منها**.
 *
 * كل حالة هنا تقابل نهايةً مختلفةً وإجراءً مختلفًا. جمعُها تحت شاشة واحدة
 * — أو تحت شريط تنبيه فوق مؤشّر دوّار — هو ما جعل العميل ينتظر بلا نهاية.
 */
describe("١٠) ما بعد التنزيل: أربع نهايات لا واحدة", () => {
  const downloaded = {
    ...signedIn,
    subscription: usable,
    planAcknowledged: true,
    download: "done",
  };

  it("لم يُفتح الملف بعد ⇒ شاشة الفتح", () => {
    expect(resolveStep(downloaded)).toBe(STEPS.INSTALLER_READY);
  });

  it("رفض المتصفح الفتح ⇒ شاشة قائمة بذاتها لا رسالة عابرة", () => {
    expect(resolveStep({ ...downloaded, openFailed: true })).toBe(
      STEPS.OPEN_FAILED,
    );
  });

  it("⚠️ رفضُ الفتح لا يضع المستخدم في الانتظار", () => {
    // `installStarted` تبقى كاذبة، وهي شرط شاشة الانتظار كلها.
    const step = resolveStep({ ...downloaded, openFailed: true });
    expect(step).not.toBe(STEPS.AWAITING_RUNTIME);
    expect(step).not.toBe(STEPS.ACTIVATING_DEVICE);
  });

  it("نجح الفتح ⇒ انتظار اكتمال التثبيت", () => {
    expect(resolveStep({ ...downloaded, installStarted: true })).toBe(
      STEPS.AWAITING_RUNTIME,
    );
  });

  it("انتهت المهلة ⇒ شاشة تشخيص لا حركة مستمرة", () => {
    expect(
      resolveStep({ ...downloaded, installStarted: true, runtimeTimedOut: true }),
    ).toBe(STEPS.INSTALL_HELP);
  });

  it("تعذّر تسليم الرمز ⇒ شاشته هو", () => {
    expect(
      resolveStep({
        ...downloaded,
        installStarted: true,
        handoverFailure: "لم يصل رمز التركيب.",
      }),
    ).toBe(STEPS.HANDOVER_FAILED);
  });

  it("رفض الخادم التفعيل ⇒ شاشة أخرى غيرها", () => {
    expect(
      resolveStep({
        ...downloaded,
        installStarted: true,
        activationFailure: "حسابك مفعّل على جهاز آخر.",
      }),
    ).toBe(STEPS.ACTIVATION_FAILED);
  });

  it("⚠️ الفشل يسبق شاشات التقدّم مهما كانت حالة الـRuntime", () => {
    // شاشة تقدّم فوق فشلٍ وقع هي «الانتظار بلا نهاية» بعينه.
    for (const runtime of [
      null,
      { needs_activation: true, is_ready: false, phase: "awaiting_activation" },
      { needs_activation: false, is_ready: false, phase: "activating" },
    ]) {
      expect(
        resolveStep({
          ...downloaded,
          runtime,
          installStarted: true,
          handingOver: true,
          activationFailure: "مرفوض",
        }),
      ).toBe(STEPS.ACTIVATION_FAILED);
    }
  });

  it("⚠️ الفشل يُعرض ولو لم يبدأ المستخدم تثبيتًا في هذه الجلسة", () => {
    // التسليم يقع عند الدخول نفسه إن كان Runtime مثبَّتًا ينتظر ربطًا.
    expect(
      resolveStep({
        ...signedIn,
        subscription: usable,
        planAcknowledged: true,
        runtime: { needs_activation: true, is_ready: false },
        handoverFailure: "لم يصل رمز التركيب.",
      }),
    ).toBe(STEPS.HANDOVER_FAILED);
  });
});

describe("١١) عنوان الانتظار يصف ما يحدث فعلًا", () => {
  it("⚠️ «بانتظار اكتمال تثبيت GovMind» لا «تفعيل الجهاز»", () => {
    // العميل قرأ «جارٍ تفعيل هذا الجهاز» بينما لا تفعيل يجري.
    expect(STEP_TITLES[STEPS.AWAITING_RUNTIME]).toBe(
      "بانتظار اكتمال تثبيت GovMind",
    );
    expect(STEP_TITLES[STEPS.AWAITING_RUNTIME]).not.toContain("تفعيل");
  });

  it("«جارٍ تفعيل الجهاز» محجوزة للتسليم الفعلي وحده", () => {
    expect(STEP_TITLES[STEPS.ACTIVATING_DEVICE]).toContain("تفعيل");
    expect(
      resolveStep({
        ...signedIn,
        subscription: usable,
        planAcknowledged: true,
        download: "done",
        installStarted: true,
        runtime: { needs_activation: true, is_ready: false, phase: "activating" },
        handingOver: true,
      }),
    ).toBe(STEPS.ACTIVATING_DEVICE);
  });

  it("عنوان المهلة يقول «لم يبدأ» لا «لم يظهر»", () => {
    expect(STEP_TITLES[STEPS.INSTALL_HELP]).toBe("لم يبدأ GovMind بعد");
  });
});

describe("١٢) الجهاز المفعَّل هو هذا الحاسب", () => {
  const takenElsewhere = {
    ...usable,
    device: { ...usable.device, is_current_device: false },
  };

  it("جهاز آخر بلا Runtime هنا ⇒ شاشة الاستبدال", () => {
    expect(
      resolveStep({ ...signedIn, subscription: takenElsewhere }),
    ).toBe(STEPS.DEVICE_TAKEN);
  });

  it("⚠️ Runtime مربوط على هذا الحاسب ينفي «جهاز آخر»", () => {
    // بصمة المتصفح التي تقارن بها `verify` ليست هوية الجهاز التي سجّلها
    // الـRuntime، فالمقارنة تعطي «جهاز آخر» على الحاسب نفسه بعد تثبيت
    // ناجح. وجودُ Runtime مربوط إثباتٌ أقوى: لا يعمل إلا هنا، ولا يُعدّ
    // مربوطًا إلا ببيان اعتماد أصدره الخادم.
    expect(
      resolveStep({
        ...signedIn,
        subscription: takenElsewhere,
        runtime: { needs_activation: false, is_ready: true },
      }),
    ).toBe(STEPS.INSTALLED);
  });

  it("Runtime ينتظر ربطًا **لا** ينفيها: لم يُربط بعد", () => {
    expect(
      resolveStep({
        ...signedIn,
        subscription: takenElsewhere,
        runtime: { needs_activation: true, is_ready: false },
      }),
    ).toBe(STEPS.DEVICE_TAKEN);
  });

  it("`isThisDeviceLinked` تقيس الربط لا الوجود", () => {
    expect(isThisDeviceLinked(null)).toBe(false);
    expect(isThisDeviceLinked({ needs_activation: true })).toBe(false);
    expect(isThisDeviceLinked({ needs_activation: false })).toBe(true);
  });
});

describe("١٣) استئناف بعد إغلاق النافذة", () => {
  it("⚠️ Runtime بدأ والنافذة مغلقة ⇒ إعادة الفتح تلتقط النجاح", () => {
    // النافذة تُغلق بفقد التركيز — وهو ما يحدث حتمًا عند فتح المثبّت.
    expect(
      resolveStep({
        ...signedIn,
        subscription: usable,
        planAcknowledged: true,
        download: "done",
        installStarted: true,
        runtime: { needs_activation: false, is_ready: true },
      }),
    ).toBe(STEPS.INSTALLED);
  });

  it("Runtime يجهّز المودل ⇒ شاشة تقدّم لا شاشة تنزيل", () => {
    expect(
      resolveStep({
        ...signedIn,
        subscription: usable,
        planAcknowledged: true,
        download: "done",
        installStarted: true,
        runtime: {
          needs_activation: false,
          is_ready: false,
          phase: "downloading_model",
        },
      }),
    ).toBe(STEPS.PREPARING_MODEL);
  });

  it("تنزيل مكتمل ورفضٌ للفتح ⇒ العودة إلى شاشة الفتح لا إلى التنزيل", () => {
    expect(
      resolveStep({
        ...signedIn,
        subscription: usable,
        planAcknowledged: true,
        download: "done",
        openFailed: true,
      }),
    ).toBe(STEPS.OPEN_FAILED);
  });
});
