"use client";

import Alert from "@/components/ui/Alert";
import ErrorNotice from "@/components/ui/ErrorNotice";
import {
  SUBSCRIPTION_LABELS,
  daysUntil,
  formatDate,
  type Subscription,
} from "@/lib/admin";
import type { Failure } from "@/lib/errors";

/** التنبيه يبدأ قبل الانتهاء بشهر: تجديد الرخصة إجراء إداري لا لحظي. */
const WARNING_WINDOW_DAYS = 30;

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="gv-stat">
      <p className="gv-stat__label">{label}</p>
      <p className="gv-stat__value">{value}</p>
    </div>
  );
}

/**
 * حالة الاشتراك والمقاعد.
 *
 * **كل رقم هنا من `GET /api/organizations/{id}/subscription`** — لا قيمة
 * ثابتة في الكود. حتى عتبة التنبيه أعلاه ليست رقمًا معروضًا بل سياسة عرض.
 */
export default function SubscriptionCard({
  subscription,
  isLoading,
  failure,
  onRetry,
}: {
  subscription: Subscription | null;
  isLoading: boolean;
  failure: Failure | null;
  onRetry: () => void;
}) {
  if (isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-3" aria-label="جارٍ تحميل الاشتراك">
        <div className="gv-skeleton h-20" />
        <div className="gv-skeleton h-20" />
        <div className="gv-skeleton h-20" />
      </div>
    );
  }

  if (failure) return <ErrorNotice failure={failure} onRetry={onRetry} />;

  if (!subscription) {
    return (
      <Alert tone="warning">
        لم تصل بيانات الاشتراك. أعد التحميل، وإن تكرر فراجع مزوّد الخدمة.
      </Alert>
    );
  }

  const remainingDays = daysUntil(subscription.expires_at);
  const seatsFull = subscription.seats_available === 0;
  const nearExpiry = remainingDays > 0 && remainingDays <= WARNING_WINDOW_DAYS;

  return (
    <div className="space-y-4">
      {/* الاشتراك ممنوع الاستخدام: السبب من الـBackend وفيه تاريخ الانتهاء. */}
      {!subscription.is_usable && (
        <Alert tone="error">
          {subscription.blocked_reason ??
            "اشتراك جهتك لا يسمح باستخدام الخدمة حاليًا. راجع مزوّد الخدمة."}
        </Alert>
      )}

      {subscription.is_usable && nearExpiry && (
        <Alert tone="warning">
          يتبقى على انتهاء اشتراك جهتك {remainingDays.toLocaleString("ar")} يومًا
          ({formatDate(subscription.expires_at)}). راجع مزوّد الخدمة للتجديد قبل
          توقّف الخدمة عن جميع الموظفين.
        </Alert>
      )}

      {seatsFull && (
        <Alert tone="warning">
          استُهلكت كل المقاعد ({subscription.seats.toLocaleString("ar")}). إضافة
          موظف جديد سترفض حتى تعطّل حسابًا قائمًا أو تزيد عدد المقاعد.
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Metric
          label="حالة الاشتراك"
          value={SUBSCRIPTION_LABELS[subscription.status]}
        />
        <Metric
          label="المقاعد المستخدمة"
          value={`${subscription.seats_used.toLocaleString("ar")} من ${subscription.seats.toLocaleString("ar")}`}
        />
        <Metric
          label="تاريخ الانتهاء"
          value={formatDate(subscription.expires_at)}
        />
      </div>

      <p className="gv-hint">
        تجديد الاشتراك وزيادة المقاعد من مزوّد الخدمة لا من داخل اللوحة: هو
        قرار من يقدّم الخدمة لا من يستهلكها.
      </p>
    </div>
  );
}
