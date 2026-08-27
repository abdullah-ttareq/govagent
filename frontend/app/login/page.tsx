"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import Button from "@/components/ui/Button";
import ErrorNotice from "@/components/ui/ErrorNotice";
import Input from "@/components/ui/Input";
import { validateEmail, validatePassword } from "@/lib/auth";
import { describeFailureDetail, type Failure } from "@/lib/errors";

export default function LoginPage() {
  const { status, signIn } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
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
    setFailure(null);

    if (nextEmailError || nextPasswordError) return;

    setIsSubmitting(true);
    try {
      await signIn(email.trim(), password);
      router.replace("/");
    } catch (caught) {
      setFailure(describeFailureDetail(caught, "تعذّر تسجيل الدخول. حاول مرة أخرى."));
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

            {failure && <ErrorNotice failure={failure} />}

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

        <p className="mt-5 text-center text-xs leading-relaxed text-muted">
          نسيت كلمة المرور؟ راجع مسؤول النظام في جهتك لإعادة تعيينها.
        </p>

        <p className="mt-2 text-center text-xs">
          <Link href="/settings" className="font-semibold text-brand hover:underline">
            ضبط رابط سيرفر الجهة
          </Link>
        </p>
      </div>
    </main>
  );
}
