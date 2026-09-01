"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Alert from "@/components/ui/Alert";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import { NetworkError, OFFLINE_MESSAGE } from "@/lib/api";
import {
  DEFAULT_SERVER_URL,
  IS_DESKTOP,
  getServerUrl,
  hasStoredServerUrl,
  normalizeServerUrl,
  resetServerUrl,
  storeServerUrl,
  validateServerUrl,
  type HealthResponse,
} from "@/lib/server-url";

type TestResult =
  | { tone: "success"; text: string }
  | { tone: "error"; text: string };

/**
 * إعدادات رابط سيرفر الجهة.
 *
 * **غير محمية عمدًا.** هذه الصفحة هي ما يحتاجه الموظف حين يكون الرابط خطأ،
 * وحينها يفشل `/api/auth/me` فيحوّله `RequireAuth` إلى `/login` — فلو كانت
 * محمية لما أمكن الوصول إليها لإصلاح السبب. ولا تكشف شيئًا: كل ما فيها قيمة
 * محفوظة في متصفح الموظف نفسه.
 */
export default function SettingsPage() {
  const [value, setValue] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [isCustom, setIsCustom] = useState(false);

  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  // القيمة المحفوظة لا تُقرأ إلا في المتصفح، فتُملأ بعد أول تركيب.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setValue(getServerUrl());
    setIsCustom(hasStoredServerUrl());
  }, []);

  function handleSave(event: React.FormEvent) {
    event.preventDefault();

    const invalid = validateServerUrl(value);
    setFieldError(invalid);
    setSaved(false);
    // نتيجة فحص قديمة تخصّ عنوانًا آخر — تُمسح حتى لا تُقرأ على أنها للجديد.
    setTestResult(null);
    if (invalid) return;

    const cleaned = normalizeServerUrl(value);
    storeServerUrl(cleaned);
    setValue(cleaned);
    setIsCustom(true);
    setSaved(true);
  }

  function handleReset() {
    resetServerUrl();
    setValue(DEFAULT_SERVER_URL);
    setIsCustom(false);
    setFieldError(null);
    setTestResult(null);
    setSaved(true);
  }

  /**
   * يفحص العنوان المكتوب في الحقل، لا المحفوظ: الموظف يجرّب قبل أن يحفظ.
   * `/health` هو المسار الوحيد الذي يعمل بلا رمز دخول.
   */
  async function handleTest() {
    const invalid = validateServerUrl(value);
    setFieldError(invalid);
    if (invalid) return;

    setIsTesting(true);
    setTestResult(null);

    const target = normalizeServerUrl(value);
    // مهلة صريحة: عنوان لا يردّ يترك الطلب معلّقًا دقائق بلا هذه.
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);

    try {
      const response = await fetch(`${target}/health`, {
        signal: controller.signal,
      });

      if (!response.ok) {
        setTestResult({
          tone: "error",
          text: `العنوان يستجيب لكن ليس بخدمة GovMind (رد بالحالة ${response.status}). تأكد من الرابط والمنفذ.`,
        });
        return;
      }

      const health = (await response.json()) as HealthResponse;
      setTestResult({
        tone: "success",
        text: `الاتصال ناجح. الخدمة تعمل، ومزود المودل: ${health.model_provider}.`,
      });
    } catch (caught) {
      const isTimeout =
        caught instanceof DOMException && caught.name === "AbortError";
      setTestResult({
        tone: "error",
        text: isTimeout
          ? "انتهت مهلة الاتصال بلا رد. تأكد من تشغيل السيرفر ومن أن الجهاز على شبكة الجهة."
          : caught instanceof NetworkError
            ? caught.message
            : OFFLINE_MESSAGE,
      });
    } finally {
      clearTimeout(timeout);
      setIsTesting(false);
    }
  }

  return (
    <main className="mx-auto min-h-dvh w-full max-w-2xl px-4 py-8 sm:py-12">
      <Link href="/" className="text-sm font-semibold text-brand hover:underline">
        → العودة إلى المحادثات
      </Link>

      <h1 className="mt-6 text-xl font-bold">الإعدادات</h1>

      {/*
        ⚠️ **حقل رابط السيرفر يختفي في نسخة سطح المكتب.**
        هناك تخدم الواجهةَ وGovMind Runtime عمليةٌ واحدة على الاسترجاع
        المحلي، فالعنوان النسبي هو الصحيح دائمًا. عرضُ حقلٍ يستطيع العميل
        أن يكسر به تطبيقه لا فائدة منه، والشرط صريح: لا يُدخل العميل
        عنوانًا ولا منفذًا.
      */}
      {IS_DESKTOP ? (
        <section className="mt-5 rounded-lg border border-border-subtle bg-surface p-5 sm:p-6">
          <h2 className="text-lg font-bold">الاتصال</h2>
          <p className="mt-2 text-sm text-muted">
            يعمل GovMind على هذا الجهاز، ولا يحتاج إعداد أي عنوان.
          </p>
        </section>
      ) : (
      <section className="mt-5 rounded-lg border border-border-subtle bg-surface p-5 sm:p-6">
        <h2 className="text-lg font-bold">رابط سيرفر الجهة</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          العنوان الذي نُشر عليه GovMind داخل جهتك. يُحفظ في هذا المتصفح
          وحده، ويُستخدم في كل الطلبات بعد الحفظ.
        </p>

        <form onSubmit={handleSave} noValidate className="mt-5">
          <Input
            label="العنوان"
            dir="ltr"
            inputMode="url"
            autoCapitalize="none"
            spellCheck={false}
            placeholder="http://10.0.0.5:8000"
            hint={`الافتراضي: ${DEFAULT_SERVER_URL}`}
            value={value}
            error={fieldError}
            disabled={isTesting}
            onChange={(event) => {
              setValue(event.target.value);
              if (fieldError) setFieldError(null);
              setSaved(false);
            }}
          />

          <div className="mt-5 flex flex-col gap-2 sm:flex-row">
            <Button type="submit">حفظ العنوان</Button>

            <Button
              type="button"
              variant="secondary"
              onClick={handleTest}
              isLoading={isTesting}
              loadingLabel="جارٍ الفحص…"
            >
              اختبار الاتصال
            </Button>

            {isCustom && (
              <Button
                type="button"
                variant="ghost"
                onClick={handleReset}
                disabled={isTesting}
              >
                استعادة الافتراضي
              </Button>
            )}
          </div>
        </form>

        {saved && (
          <Alert tone="success" className="mt-5">
            حُفظ العنوان. كل الطلبات التالية ستستخدمه.
          </Alert>
        )}

        {testResult && (
          <Alert tone={testResult.tone} className="mt-3">
            {testResult.text}
          </Alert>
        )}
      </section>
      )}

      {!IS_DESKTOP && (
        <p className="mt-5 text-xs leading-relaxed text-muted">
          لا تعرف العنوان؟ اطلبه من مسؤول النظام في جهتك. لا تُدخل هنا عنوان
          سيرفر لا يخصّ جهتك.
        </p>
      )}
    </main>
  );
}
