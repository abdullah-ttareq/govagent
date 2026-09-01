/**
 * حراسة قائمة المظهر في الموقع.
 *
 * ما تمنعه هذه الاختبارات من الرجوع:
 * 1. عودة خيار «تلقائي / الجهاز» إلى الموقع (بقاؤه في الإضافة مقصود).
 * 2. بقاء قيمة `system` أو `auto` مخزّنة بلا تحويل، فلا يقابلها خيار في
 *    القائمة ولا تظهر علامة صح على شيء.
 */

import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_THEME,
  THEME_CHOICES,
  THEME_INIT_SCRIPT,
  THEME_STORAGE_KEY,
  isThemeChoice,
  normalizeStoredTheme,
  readStoredTheme,
  setThemeChoice,
} from "@/lib/theme";

beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("خيارات المظهر في الموقع", () => {
  it("خياران فقط: فاتح وداكن", () => {
    expect(THEME_CHOICES).toEqual(["light", "dark"]);
  });

  it("لا يقبل system ولا auto كاختيار صالح", () => {
    expect(isThemeChoice("system")).toBe(false);
    expect(isThemeChoice("auto")).toBe(false);
    expect(isThemeChoice("light")).toBe(true);
    expect(isThemeChoice("dark")).toBe(true);
  });

  it("الافتراضي فاتح", () => {
    expect(DEFAULT_THEME).toBe("light");
  });
});

describe("تحويل القيم القديمة عند القراءة", () => {
  it.each(["system", "auto"])("%s المخزّنة تُقرأ فاتحًا", (legacy) => {
    window.localStorage.setItem(THEME_STORAGE_KEY, legacy);
    expect(readStoredTheme()).toBe("light");
  });

  it("لا يغيّر مفتاح التخزين", () => {
    expect(THEME_STORAGE_KEY).toBe("govagent.theme");
  });

  it("قيمة غريبة أو غائبة تُقرأ فاتحًا", () => {
    expect(normalizeStoredTheme("purple")).toBe("light");
    expect(normalizeStoredTheme(null)).toBe("light");
    expect(normalizeStoredTheme(undefined)).toBe("light");
    expect(readStoredTheme()).toBe("light");
  });

  it("الاختيار الصالح يُقرأ كما هو", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(readStoredTheme()).toBe("dark");
  });
});

describe("حفظ الاختيار", () => {
  it("يُحفظ ويُطبَّق ويبقى بعد إعادة القراءة", () => {
    setThemeChoice("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    // إعادة القراءة تحاكي تحديث الصفحة.
    expect(readStoredTheme()).toBe("dark");

    setThemeChoice("light");
    expect(readStoredTheme()).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("سكربت ما قبل الرسم", () => {
  it("لا يذكر prefers-color-scheme بعد إزالة «تلقائي»", () => {
    expect(THEME_INIT_SCRIPT).not.toContain("prefers-color-scheme");
  });

  it.each([
    ["dark", "dark"],
    ["light", "light"],
    ["system", "light"],
    ["auto", "light"],
    [null, "light"],
  ])("القيمة المخزّنة %s تعطي %s قبل إقلاع React", (stored, expected) => {
    if (stored !== null) window.localStorage.setItem(THEME_STORAGE_KEY, stored);
    // يُنفَّذ السكربت نفسه الذي يُحقن في <head>.
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.dataset.theme).toBe(expected);
  });
});
