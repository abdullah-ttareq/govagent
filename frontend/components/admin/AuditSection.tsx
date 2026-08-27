"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import ErrorNotice from "@/components/ui/ErrorNotice";
import { ApiError } from "@/lib/api";
import type { DirectoryUser } from "@/lib/admin";
import {
  ACTION_LABELS,
  AUDIT_PAGE_SIZE,
  describeAction,
  formatEventTime,
  listAuditLogs,
  toLocalDateKey,
  type AuditEvent,
} from "@/lib/audit";
import { describeFailureDetail, type Failure } from "@/lib/errors";

export default function AuditSection({ users }: { users: DirectoryUser[] }) {
  const { token, endExpiredSession } = useAuth();

  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [failure, setFailure] = useState<Failure | null>(null);

  // تصفية يدعمها الـBackend مباشرة.
  const [action, setAction] = useState("");
  const [userId, setUserId] = useState("");
  // تصفية بالتاريخ: الـBackend لا يوفّر معامل تاريخ، فتُطبَّق على الصفحة
  // المعروضة وحدها، ويُقال ذلك صراحة تحت الجدول بدل الإيهام بأنها شاملة.
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  const load = useCallback(
    async (nextOffset: number, signal?: AbortSignal) => {
      if (!token) return;
      setIsLoading(true);
      try {
        const result = await listAuditLogs(
          token,
          {
            action: action || null,
            userId: userId ? Number(userId) : null,
            offset: nextOffset,
          },
          signal,
        );
        setEvents(result.events);
        setTotal(result.page.total);
        setOffset(result.page.offset);
        setFailure(null);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setFailure(describeFailureDetail(caught, "تعذّر تحميل سجل التدقيق."));
        if (caught instanceof ApiError && caught.status === 401) endExpiredSession();
      } finally {
        setIsLoading(false);
      }
    },
    [token, action, userId, endExpiredSession],
  );

  // تغيير التصفية يعيد الترقيم إلى أوله: الصفحة الخامسة من نتيجة قديمة
  // لا معنى لها في نتيجة جديدة.
  useEffect(() => {
    const controller = new AbortController();
    // جلب أولي من السيرفر — النمط الذي تستثنيه القاعدة نفسها: مزامنة مع
    // نظام خارجي، والكتابة تحدث بعد انتهاء الطلب لا داخل التصيير.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(0, controller.signal);
    return () => controller.abort();
  }, [load]);

  const nameById = useMemo(() => {
    const map = new Map<number, string>();
    users.forEach((item) => map.set(item.id, item.full_name));
    return map;
  }, [users]);

  const visible = useMemo(
    () =>
      events.filter((event) => {
        const day = toLocalDateKey(event.created_at);
        if (fromDate && day < fromDate) return false;
        if (toDate && day > toDate) return false;
        return true;
      }),
    [events, fromDate, toDate],
  );

  const pageNumber = Math.floor(offset / AUDIT_PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(total / AUDIT_PAGE_SIZE));
  const hasDateFilter = Boolean(fromDate || toDate);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="gv-field">
          <label className="gv-label" htmlFor="audit-action">
            نوع الحدث
          </label>
          <select
            id="audit-action"
            className="gv-input"
            value={action}
            onChange={(event) => setAction(event.target.value)}
          >
            <option value="">كل الأنواع</option>
            {Object.entries(ACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div className="gv-field">
          <label className="gv-label" htmlFor="audit-user">
            الموظف
          </label>
          <select
            id="audit-user"
            className="gv-input"
            value={userId}
            onChange={(event) => setUserId(event.target.value)}
          >
            <option value="">كل الموظفين</option>
            {users.map((item) => (
              <option key={item.id} value={item.id}>
                {item.full_name}
              </option>
            ))}
          </select>
        </div>

        <div className="gv-field">
          <label className="gv-label" htmlFor="audit-from">
            من تاريخ
          </label>
          <input
            id="audit-from"
            type="date"
            dir="ltr"
            className="gv-input"
            value={fromDate}
            max={toDate || undefined}
            onChange={(event) => setFromDate(event.target.value)}
          />
        </div>

        <div className="gv-field">
          <label className="gv-label" htmlFor="audit-to">
            إلى تاريخ
          </label>
          <input
            id="audit-to"
            type="date"
            dir="ltr"
            className="gv-input"
            value={toDate}
            min={fromDate || undefined}
            onChange={(event) => setToDate(event.target.value)}
          />
        </div>
      </div>

      {isLoading ? (
        <ul className="space-y-2" aria-label="جارٍ تحميل السجل">
          {[0, 1, 2, 3, 4].map((index) => (
            <li key={index} className="gv-skeleton h-12" />
          ))}
        </ul>
      ) : failure ? (
        <ErrorNotice failure={failure} onRetry={() => void load(offset)} />
      ) : visible.length === 0 ? (
        <EmptyState
          title={
            events.length === 0
              ? "لا توجد أحداث مطابقة."
              : "لا توجد أحداث في هذا النطاق الزمني ضمن الصفحة المعروضة."
          }
          hint={
            events.length === 0
              ? "غيّر التصفية، أو انتظر حتى تقع أحداث جديدة في جهتك."
              : "التصفية بالتاريخ تعمل على الصفحة المعروضة. تنقّل بين الصفحات أو وسّع النطاق."
          }
          action={
            (action || userId || hasDateFilter) && (
              <Button
                variant="secondary"
                onClick={() => {
                  setAction("");
                  setUserId("");
                  setFromDate("");
                  setToDate("");
                }}
              >
                مسح التصفية
              </Button>
            )
          }
        />
      ) : (
        <div className="gv-table-wrap">
          <table className="gv-table">
            <thead>
              <tr>
                <th scope="col">الوقت</th>
                <th scope="col">الموظف</th>
                <th scope="col">نوع الحدث</th>
                <th scope="col">التفاصيل</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((event) => (
                <tr key={event.id}>
                  <td className="whitespace-nowrap text-xs">
                    {formatEventTime(event.created_at)}
                  </td>
                  <td className="text-sm">
                    {/* حدث بلا صاحب: تجهيز الجهة يسبق وجود أي مستخدم. */}
                    {event.user_id === null
                      ? "—"
                      : (nameById.get(event.user_id) ??
                        `موظف #${event.user_id.toLocaleString("ar")}`)}
                  </td>
                  <td>
                    <span className="gv-badge">{describeAction(event.action)}</span>
                  </td>
                  <td className="text-sm text-muted">{event.details ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!failure && total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted">
            صفحة {pageNumber.toLocaleString("ar")} من{" "}
            {pageCount.toLocaleString("ar")} · {total.toLocaleString("ar")} حدث
            {hasDateFilter &&
              ` · معروض منها ${visible.length.toLocaleString("ar")} بعد التصفية بالتاريخ`}
          </p>

          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={offset === 0 || isLoading}
              onClick={() => void load(Math.max(0, offset - AUDIT_PAGE_SIZE))}
            >
              الأحدث
            </Button>
            <Button
              variant="secondary"
              disabled={offset + AUDIT_PAGE_SIZE >= total || isLoading}
              onClick={() => void load(offset + AUDIT_PAGE_SIZE)}
            >
              الأقدم
            </Button>
          </div>
        </div>
      )}

      {hasDateFilter && (
        <p className="gv-hint">
          التصفية بالتاريخ تُطبَّق على الصفحة المعروضة: مسار سجل التدقيق في
          الـBackend يوفّر تصفية بالنوع وبالموظف فقط، بلا معامل تاريخ.
        </p>
      )}
    </div>
  );
}
