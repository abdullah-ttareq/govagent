"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import AuditSection from "@/components/admin/AuditSection";
import SubscriptionCard from "@/components/admin/SubscriptionCard";
import UsersSection from "@/components/admin/UsersSection";
import {
  getSubscription,
  listUsers,
  type DirectoryUser,
  type Subscription,
} from "@/lib/admin";
import { describeFailureDetail, type Failure } from "@/lib/errors";

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border-subtle bg-surface p-5 sm:p-6">
      <h2 className="text-lg font-bold">{title}</h2>
      <p className="mt-1 text-sm leading-relaxed text-muted">{description}</p>
      <div className="mt-5">{children}</div>
    </section>
  );
}

/**
 * لوحة مسؤول الجهة.
 *
 * قائمة الموظفين تُقرأ هنا **مرة واحدة** وتُمرَّر إلى سجل التدقيق: السجل
 * يعيد `user_id` لا اسمًا، وترجمة كل معرّف بنداء مستقل تعني عشرات الطلبات
 * لصفحة واحدة.
 */
export default function AdminDashboard() {
  const { token, user } = useAuth();

  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [isLoadingSubscription, setIsLoadingSubscription] = useState(true);
  const [subscriptionFailure, setSubscriptionFailure] = useState<Failure | null>(null);

  const [users, setUsers] = useState<DirectoryUser[]>([]);

  const organizationId = user?.organization_id;

  const loadSubscription = useCallback(
    async (signal?: AbortSignal) => {
      if (!token || !organizationId) return;
      try {
        setSubscription(await getSubscription(token, organizationId, signal));
        setSubscriptionFailure(null);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setSubscriptionFailure(
          describeFailureDetail(caught, "تعذّر تحميل بيانات الاشتراك."),
        );
      } finally {
        setIsLoadingSubscription(false);
      }
    },
    [token, organizationId],
  );

  const loadUsers = useCallback(
    async (signal?: AbortSignal) => {
      if (!token) return;
      try {
        setUsers((await listUsers(token, signal)).users);
      } catch {
        // فشل هنا لا يُعرض: `UsersSection` يجلب القائمة بنفسه ويعرض خطأه.
        // هذه النسخة لأسماء سجل التدقيق فقط، وبديلها معرّف رقمي مقبول.
      }
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    // جلب أولي من السيرفر — النمط الذي تستثنيه القاعدة نفسها: مزامنة مع
    // نظام خارجي، والكتابة تحدث بعد انتهاء الطلب لا داخل التصيير.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSubscription(controller.signal);
    void loadUsers(controller.signal);
    return () => controller.abort();
  }, [loadSubscription, loadUsers]);

  /** تغيّر في الموظفين يمسّ المقاعد، فتُعاد قراءة الاشتراك والأسماء. */
  const handleDirectoryChanged = useCallback(() => {
    void loadSubscription();
    void loadUsers();
  }, [loadSubscription, loadUsers]);

  return (
    <main className="mx-auto min-h-dvh w-full max-w-5xl px-4 py-8 sm:py-10">
      <Link href="/" className="text-sm font-semibold text-brand hover:underline">
        → العودة إلى المحادثات
      </Link>

      <header className="mt-6">
        <h1 className="text-xl font-bold">لوحة مسؤول الجهة</h1>
        <p className="mt-1 text-sm text-muted">
          {user?.organization_name ?? "جهتك"}
        </p>
      </header>

      <div className="mt-6 space-y-5">
        <Section
          title="الاشتراك والتراخيص"
          description="حالة اشتراك جهتك والمقاعد المستهلَكة، كما يعيدها السيرفر."
        >
          <SubscriptionCard
            subscription={subscription}
            isLoading={isLoadingSubscription}
            failure={subscriptionFailure}
            onRetry={() => {
              setIsLoadingSubscription(true);
              void loadSubscription();
            }}
          />
        </Section>

        <Section
          title="الموظفون"
          description="موظفو جهتك وحدها. إضافة وتغيير دور وتعطيل وإعادة تفعيل."
        >
          <UsersSection onDirectoryChanged={handleDirectoryChanged} />
        </Section>

        <Section
          title="سجل التدقيق"
          description="من فعل ماذا ومتى داخل جهتك. السجل للقراءة فقط، ولا يُعدَّل ولا يُحذف منه."
        >
          <AuditSection users={users} />
        </Section>
      </div>
    </main>
  );
}
