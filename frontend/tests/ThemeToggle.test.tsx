/**
 * مبدّل المظهر: **زرّ واحد ينقل مباشرة بين وضعين**.
 *
 * ما يثبته هذا الملف:
 *
 * * وضعان لا ثلاثة، وبلا «تلقائي» ولا «الجهاز» ولا أيقونة شاشة.
 * * الأيقونة تصف **الفعل** لا الحالة: قمرٌ في الفاتح، وشمسٌ في الداكن.
 * * نقرة واحدة تكفي — لا قائمة ولا خطوة ثانية.
 * * الاختيار يُحفظ ويُطبَّق ويبقى بعد إعادة التحميل.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import ThemeToggle from "@/components/ThemeToggle";
import { THEME_STORAGE_KEY } from "@/lib/theme";

const LIGHT_LABEL = "تفعيل الوضع الفاتح";
const DARK_LABEL = "تفعيل الوضع الداكن";

/** شريحة الشمس: فعلها «تفعيل الوضع الفاتح». */
function sun() {
  return screen.getByRole("button", { name: LIGHT_LABEL });
}

/** شريحة القمر: فعلها «تفعيل الوضع الداكن». */
function moon() {
  return screen.getByRole("button", { name: DARK_LABEL });
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(cleanup);

// ===========================================================================
// ١) وضعان فقط
// ===========================================================================
describe("وضعان لا ثلاثة", () => {
  it("شريحتان فقط — لا خيار ثالث ولا قائمة", () => {
    render(<ThemeToggle />);

    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.queryAllByRole("menuitemradio")).toHaveLength(0);
  });

  it("⚠️ لا «تلقائي» ولا «الجهاز» ولا أي مرادف", () => {
    // وضعٌ يتبع الجهاز يتبدّل تحت يد الموظف بلا فعل منه.
    render(<ThemeToggle />);
    const markup = document.body.innerHTML;

    for (const word of ["تلقائي", "الجهاز", "النظام", "system", "auto"]) {
      expect(markup).not.toContain(word);
    }
  });

  it("⚠️ لا أيقونة شاشة أو حاسب — شمس وقمر فقط", () => {
    // أيقونة شاشة تعني وضعًا ثالثًا لا وجود له، فتَعِد بما لا يُنفَّذ.
    const { container } = render(<ThemeToggle />);

    expect(container.querySelectorAll("svg")).toHaveLength(2);
    expect(container.querySelectorAll("rect")).toHaveLength(0);
  });
});

// ===========================================================================
// ٢) الأيقونة تصف الفعل لا الحالة
// ===========================================================================
describe("الأيقونة والنصّ يصفان الفعل", () => {
  it("في الوضع الفاتح: الشمس مضغوطة والقمر لا", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(<ThemeToggle />);

    expect(sun().getAttribute("aria-pressed")).toBe("true");
    expect(moon().getAttribute("aria-pressed")).toBe("false");
  });

  it("في الوضع الداكن: القمر مضغوط والشمس لا", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    render(<ThemeToggle />);

    expect(moon().getAttribute("aria-pressed")).toBe("true");
    expect(sun().getAttribute("aria-pressed")).toBe("false");
  });

  it("⚠️ الأيقونتان مختلفتان فعلًا", () => {
    // لو رُسمت الأيقونة نفسها في الشريحتين، لصارتا لا تقولان شيئًا.
    const { container } = render(<ThemeToggle />);
    const paths = [...container.querySelectorAll("path")].map((n) =>
      n.getAttribute("d"),
    );

    expect(paths).toHaveLength(2);
    expect(paths[0]).not.toBe(paths[1]);
  });
});

// ===========================================================================
// ٣) نقرة واحدة تبدّل
// ===========================================================================
describe("التبديل المباشر", () => {
  it("من الفاتح إلى الداكن بنقرة واحدة", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(<ThemeToggle />);

    fireEvent.click(moon());

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(moon().getAttribute("aria-pressed")).toBe("true");
  });

  it("ومن الداكن إلى الفاتح بنقرة واحدة", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    render(<ThemeToggle />);

    fireEvent.click(sun());

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(sun().getAttribute("aria-pressed")).toBe("true");
  });

  it("نقرتان تعيدان الوضع كما كان", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(<ThemeToggle />);

    fireEvent.click(moon());
    fireEvent.click(sun());

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });
});

// ===========================================================================
// ٤) البقاء بعد إعادة التحميل
// ===========================================================================
describe("حفظ الاختيار", () => {
  it("⚠️ الاختيار يبقى بعد إعادة تركيب الصفحة", () => {
    // إعادةُ التركيب تحاكي تحديث الصفحة وإعادة تشغيل الـRuntime: المصدر
    // في الحالتين هو `localStorage` نفسه.
    render(<ThemeToggle />);
    fireEvent.click(moon());
    cleanup();

    render(<ThemeToggle />);

    expect(moon().getAttribute("aria-pressed")).toBe("true");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("قيمة `system` قديمة تُقرأ فاتحًا لا وضعًا ثالثًا", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "system");
    render(<ThemeToggle />);

    expect(sun().getAttribute("aria-pressed")).toBe("true");
  });

  it("قيمة تالفة لا تكسر الزرّ", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "لا شيء");
    render(<ThemeToggle />);

    expect(sun().getAttribute("aria-pressed")).toBe("true");
  });
});
