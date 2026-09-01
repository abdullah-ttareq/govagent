/**
 * التنزيل: التقدّم، والإلغاء، وفشل الشبكة، وعدم تشغيل أي ملف.
 *
 * يمرّ كل اختبار على `chrome.downloads` المزيّف في `setup.js`، وهو يحاكي
 * سلوك المتصفح بحالة تتغيّر لا باستدعاء يعيد رقمًا.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cancelDownload,
  describeInterruption,
  formatBytes,
  percentOf,
  queryDownload,
  showInFolder,
  startDownload,
  watchDownload,
} from "../lib/download.js";

const SIGNED_URL =
  "https://acct.blob.core.windows.net/releases/GovMindSetup.exe?sv=2022-11-02&sig=xyz";

afterEach(() => {
  vi.useRealTimers();
});

describe("بدء التنزيل", () => {
  it("يمرّر الرابط إلى المتصفح بلا نافذة اختيار مكان", async () => {
    const id = await startDownload(SIGNED_URL, "GovMindSetup.exe");

    expect(id).toBe(1);
    expect(chrome.downloads.download).toHaveBeenCalledWith(
      { url: SIGNED_URL, filename: "GovMindSetup.exe", saveAs: false },
      expect.any(Function),
    );
  });

  it("يرفع رسالة عربية إن رفض المتصفح التنزيل", async () => {
    chrome.downloads.__refuse = true;
    await expect(startDownload(SIGNED_URL, "x.exe")).rejects.toThrow(
      /تعذّر بدء التنزيل/,
    );
  });

  it("لا تحمل رسالة الفشل الرابط الموقّع", async () => {
    chrome.downloads.__refuse = true;
    // رسالة `lastError` من Chrome قد تضمّ الرابط؛ نصّنا مكتوب يدويًا بدلها.
    await expect(startDownload(SIGNED_URL, "x.exe")).rejects.toThrow(
      /^(?!.*sig=).*$/s,
    );
  });
});

describe("النسبة والحجم", () => {
  it("يحسب النسبة من البايتات", () => {
    expect(percentOf({ bytesReceived: 50, totalBytes: 200 })).toBe(25);
    expect(percentOf({ bytesReceived: 200, totalBytes: 200 })).toBe(100);
  });

  it("يعيد null لا صفرًا حين يكون الحجم الكلي مجهولًا", () => {
    // «٠٪» على تنزيل يجري تقول للمستخدم إن شيئًا لم يبدأ، وهذا خطأ.
    expect(percentOf({ bytesReceived: 900, totalBytes: 0 })).toBeNull();
    expect(percentOf({})).toBeNull();
  });

  it("لا يتجاوز مئة بالمئة", () => {
    expect(percentOf({ bytesReceived: 300, totalBytes: 200 })).toBe(100);
  });

  it("يصوغ الحجم بوحدات عربية", () => {
    expect(formatBytes(512)).toBe("512 بايت");
    expect(formatBytes(2048)).toBe("2 ك.ب");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 م.ب");
    expect(formatBytes(0)).toBe("غير معروف");
  });
});

describe("متابعة التقدّم", () => {
  it("يبلّغ بالتقدّم ثم بالاكتمال", async () => {
    vi.useFakeTimers();
    const id = await startDownload(SIGNED_URL, "GovMindSetup.exe");

    const onProgress = vi.fn();
    const onDone = vi.fn();
    const onFail = vi.fn();
    watchDownload(id, { onProgress, onDone, onFail });

    chrome.downloads.__advance(id, 50, 200);
    await vi.advanceTimersByTimeAsync(500);
    expect(onProgress).toHaveBeenCalled();
    expect(percentOf(onProgress.mock.lastCall[0])).toBe(25);

    chrome.downloads.__finish(id);
    await vi.advanceTimersByTimeAsync(500);
    expect(onDone).toHaveBeenCalledOnce();
    expect(onFail).not.toHaveBeenCalled();
  });

  it("يبلّغ بالفشل برسالة عربية عند انقطاع الشبكة", async () => {
    vi.useFakeTimers();
    const id = await startDownload(SIGNED_URL, "x.exe");

    const onFail = vi.fn();
    const onDone = vi.fn();
    watchDownload(id, { onFail, onDone });

    chrome.downloads.__finish(id, { error: "NETWORK_FAILED" });
    await vi.advanceTimersByTimeAsync(500);

    expect(onDone).not.toHaveBeenCalled();
    expect(onFail).toHaveBeenCalledWith(
      expect.stringContaining("انقطع الاتصال"),
      expect.anything(),
    );
  });

  it("يتوقّف عن الاستطلاع بعد النهاية", async () => {
    vi.useFakeTimers();
    const id = await startDownload(SIGNED_URL, "x.exe");
    watchDownload(id, {});

    chrome.downloads.__finish(id);
    await vi.advanceTimersByTimeAsync(500);
    const callsAtFinish = chrome.downloads.search.mock.calls.length;

    await vi.advanceTimersByTimeAsync(5000);
    expect(chrome.downloads.search.mock.calls.length).toBe(callsAtFinish);
  });

  it("دالة الإيقاف تُنهي المتابعة فورًا", async () => {
    vi.useFakeTimers();
    const id = await startDownload(SIGNED_URL, "x.exe");
    const onProgress = vi.fn();
    const stop = watchDownload(id, { onProgress });

    await vi.advanceTimersByTimeAsync(500);
    stop();
    onProgress.mockClear();
    await vi.advanceTimersByTimeAsync(5000);

    expect(onProgress).not.toHaveBeenCalled();
  });

  it("يعالج اختفاء سجل التنزيل بدل أن يعلّق", async () => {
    vi.useFakeTimers();
    const id = await startDownload(SIGNED_URL, "x.exe");
    const onFail = vi.fn();
    watchDownload(id, { onFail });

    chrome.downloads.__forget(id);
    await vi.advanceTimersByTimeAsync(500);

    expect(onFail).toHaveBeenCalledOnce();
  });
});

describe("الإلغاء", () => {
  it("يلغي التنزيل الجاري", async () => {
    const id = await startDownload(SIGNED_URL, "x.exe");
    await cancelDownload(id);

    const item = await queryDownload(id);
    expect(item.state).toBe("interrupted");
    expect(item.error).toBe("USER_CANCELED");
  });

  it("رسالة الإلغاء تطمئن ولا تبدو خطأً", () => {
    expect(describeInterruption("USER_CANCELED")).toContain("أُلغي التنزيل");
  });

  it("سبب مجهول له رسالة عامة لا نصّ إنجليزي خام", () => {
    const message = describeInterruption("SOME_NEW_CHROME_REASON");
    expect(message).toContain("توقّف التنزيل");
    expect(message).not.toContain("SOME_NEW_CHROME_REASON");
  });
});

describe("لا تشغيل تلقائي لأي ملف", () => {
  it("«أظهر الملف» يفتح المجلد ولا ينفّذ شيئًا", async () => {
    const id = await startDownload(SIGNED_URL, "GovMindSetup.exe");
    showInFolder(id);

    expect(chrome.downloads.show).toHaveBeenCalledWith(id);
    // `chrome.downloads.open` هو ما يشغّل الملف، ولا وجود له في الشيفرة.
    expect(chrome.downloads.open).toBeUndefined();
  });
});
