"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import Alert from "@/components/ui/Alert";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import { ApiError, NetworkError } from "@/lib/api";
import { validateEmail, validatePassword } from "@/lib/auth";

/** يترجم فشل الدخول إلى رسالة عربية واحدة واضحة. */
function describeLoginFailure(caught: unknown): string {
  if (caught instanceof NetworkError) return caught.message;

  if (caught instanceof ApiError) {
    // 401 و 403 و 409 يكتب الـBackend رسائلها العربية بنفسه، وفيها ما لا
    // تعرفه الواجهة (تاريخ انتهاء الاشتراك مثلًا)، فتُعرض كما وردت.
    if (caught.status === 401 || caught.status === 403 || caught.status === 409) {
      return caught.message;
    }
    if (caught.status === 422) {
      return "البيانات المُدخَلة غير مقبولة. راجع البريد وكلمة المرور.";
    }
    if (caught.status >= 500) {
      return "الخدمة غير متاحة حاليًا. حاول بعد قليل، وإن تكرر فراجع مسؤول النظام في جهتك.";
    }
    return caught.message;
  }

  return "تعذّر تسجيل الدخول. حاول مرة أخرى.";
}

export default function LoginPage() {
  const { status, signIn } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // من له جلسة قائمة لا يرى صفحة الدخول.
  useEffect(() => {
    if (status === "authenticated") router.replace("/");
  }, [status, router]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) return;

    const nextEmailError = validateEmail(email);
    const nextPasswordError = validatePassword(password);
    setEmailError(nextEmailError);
    setPasswordError(nextPasswordError);
    setFormError(null);

    if (nextEmailError || nextPasswordError) return;

    setIsSubmitting(true);
    try {
      await signIn(email.trim(), password);
      router.replace("/");
    } catch (caught) {
      setFormError(describeLoginFailure(caught));
      setIsSubmitting(false);
    }
    // لا إعادة تعيين عند النجاح: الصفحة تُستبدل، وإطفاء المؤشّر قبلها يومض.
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md">
        <header className="mb-6 text-center">
          <p className="text-2xl font-bold text-brand">GovAgent</p>
          <p className="mt-1 text-sm text-muted">المساعد الذكي لموظفي الجهة</p>
        </header>

        <section className="rounded-lg border border-border-subtle bg-surface p-6 shadow-sm sm:p-8">
          <h1 className="text-xl font-bold">تسجيل الدخول</h1>
          <p className="mt-2 text-sm text-muted">
            استخدم بريد العمل الذي زوّدك به مسؤول النظام في جهتك.
          </p>

          <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-5">
            <Input
              label="البريد الإلكتروني"
              type="email"
              name="email"
              // عنوان البريد لاتيني: عرضه RTL يقلب موضع النقطة و@ بصريًا.
              dir="ltr"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              placeholder="name@entity.gov.sa"
              value={email}
              disabled={isSubmitting}
              error={emailError}
              onChange={(event) => {
                setEmail(event.target.value);
                if (emailError) setEmailError(null);
              }}
            />

            <Input
              label="كلمة المرور"
              type="password"
              name="password"
              dir="ltr"
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              disabled={isSubmitting}
              error={passwordError}
              onChange={(event) => {
                setPassword(event.target.value);
                if (passwordError) setPasswordError(null);
              }}
            />

            {formError && <Alert tone="error">{formError}</Alert>}

            <Button
              type="submit"
              block
              isLoading={isSubmitting}
              loadingLabel="جارٍ تسجيل الدخول…"
            >
              تسجيل الدخول
            </Button>
          </form>
        </section>

        <p className="mt-5 text-center text-xs text-muted">
          نسيت كلمة المرور؟ راجع مسؤول النظام في جهتك لإعادة تعيينها.
        </p>
      </div>
    </main>
  );
}
