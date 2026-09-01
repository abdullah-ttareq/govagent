/**
 * حراسة قائمة المظهر كما يراها الموظف.
 *
 * تمنع رجوع: خيار «تلقائي» في القائمة، وأيقونة الكمبيوتر، وضياع اسم خيار أو
 * أيقونته، وظهور علامة الصح على أكثر من خيار، وتعطّل الإغلاق بـEscape أو
 * بالنقر خارج القائمة.
 *
 * **الموضع والقياسات لا تُختبر هنا:** jsdom لا يحسب تخطيطًا ولا يطبّق CSS
 * خارجيًا، فكل أبعاده أصفار. خروج القائمة عن الشاشة فُحص في متصفح حقيقي.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import ThemeToggle from "@/components/ThemeToggle";
import { THEME_STORAGE_KEY } from "@/lib/theme";

beforeEach(() => {
  cleanup();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

/** يرسم المبدّل ويفتح قائمته — كل اختبار يبدأ من شجرة نظيفة. */
function openMenu() {
  render(<ThemeToggle />);
  fireEvent.click(screen.getByRole("button", { name: /المظهر/ }));
  return screen.getByRole("menu");
}

describe("خيارات القائمة", () => {
  it("خياران فقط: فاتح وداكن", () => {
    const menu = openMenu();
    const items = within(menu).getAllByRole("menuitemradio");
    expect(items.map((item) => item.textContent?.trim())).toEqual([
      "فاتح",
      "داكن",
    ]);
  });

  it("لا يعرض «تلقائي» ولا أي مرادف له", () => {
    const menu = openMenu();
    expect(within(menu).queryByText("تلقائي")).toBeNull();
    expect(within(menu).queryByText("الجهاز")).toBeNull();
    expect(within(menu).queryByText(/System/i)).toBeNull();
  });

  it("لكل خيار اسم ظاهر وأيقونة", () => {
    const menu = openMenu();
    for (const item of within(menu).getAllByRole("menuitemradio")) {
      expect(item.querySelector("span")?.textContent?.trim()).toBeTruthy();
      expect(item.querySelector("svg")).not.toBeNull();
    }
  });

  it("علامة الصح على الخيار المحدد وحده", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    const menu = openMenu();
    const checked = within(menu)
      .getAllByRole("menuitemradio")
      .filter((item) => item.getAttribute("aria-checked") === "true");
    expect(checked).toHaveLength(1);
    expect(checked[0].textContent?.trim()).toBe("داكن");
    // الصح رسمٌ إضافي داخل الخيار المحدد: أيقونتان بدل واحدة.
    expect(checked[0].querySelectorAll("svg")).toHaveLength(2);
  });

  it("قيمة system القديمة لا تترك القائمة بلا خيار محدد", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "system");
    const menu = openMenu();
    const checked = within(menu)
      .getAllByRole("menuitemradio")
      .filter((item) => item.getAttribute("aria-checked") === "true");
    expect(checked).toHaveLength(1);
    expect(checked[0].textContent?.trim()).toBe("فاتح");
  });
});

describe("زرّ القائمة", () => {
  it("يصف الوضع الفعّال في الفاتح وفي الداكن", () => {
    render(<ThemeToggle />);
    expect(
      screen.getByRole("button", { name: "المظهر: فاتح" }),
    ).toBeDefined();

    cleanup();
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "المظهر: داكن" })).toBeDefined();
  });

  it("اختيار «داكن» يحفظ ويطبّق ويغلق القائمة", () => {
    const menu = openMenu();
    fireEvent.click(within(menu).getByText("داكن"));

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("إغلاق القائمة", () => {
  it("بزرّ Escape", () => {
    openMenu();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("بالنقر خارجها", () => {
    openMenu();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("النقر داخلها لا يغلقها", () => {
    const menu = openMenu();
    fireEvent.mouseDown(menu);
    expect(screen.queryByRole("menu")).not.toBeNull();
  });
});
