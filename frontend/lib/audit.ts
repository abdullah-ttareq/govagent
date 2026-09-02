/**
 * سجل التدقيق — `GET /api/audit-logs` الموجود فعلًا في
 * `backend/app/api/audit.py`. لا مسارات كتابة ولا حذف: سجلٌ يمكن تنقيحه لا
 * يصلح دليلًا.
 */

import { apiRequest } from "@/lib/api";
import type { PageMeta } from "@/lib/conversations";

/** يطابق `AuditEventOut` في `backend/app/schemas/governance.py`. */
export type AuditEvent = {
  id: number;
  action: string;
  user_id: number | null;
  details: string | null;
  created_at: string;
};

export type AuditListResponse = {
  events: AuditEvent[];
  page: PageMeta;
};

/**
 * أنواع الأحداث كما يكتبها الـBackend، وترجمتها للعرض.
 *
 * القائمة من توثيق `AuditEventOut`. نوع غير معروف يُعرض كما هو بدل أن
 * يُخفى: سجل تدقيق يُسقِط حدثًا لا يعرفه ليس سجلًا.
 */
export const ACTION_LABELS: Record<string, string> = {
  login: "تسجيل دخول",
  user_created: "إضافة موظف",
  user_disabled: "تعطيل موظف",
  conversation_deleted: "حذف محادثة",
  file_uploaded: "رفع ملف",
  file_deleted: "حذف ملف",
  model_provider_changed: "تغيير مزود المودل",
  subscription_changed: "تغيير الاشتراك",
  organization_provisioned: "تجهيز الجهة",
};

export function describeAction(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

/** عدد الأحداث في الصفحة الواحدة. */
export const AUDIT_PAGE_SIZE = 20;

export function listAuditLogs(
  token: string,
  {
    action,
    userId,
    limit = AUDIT_PAGE_SIZE,
    offset = 0,
  }: {
    action?: string | null;
    userId?: number | null;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
): Promise<AuditListResponse> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (action) query.set("action", action);
  if (userId) query.set("user_id", String(userId));

  return apiRequest<AuditListResponse>(`/api/audit-logs?${query}`, {
    token,
    signal,
  });
}

const eventTime = new Intl.DateTimeFormat("ar", {
  dateStyle: "medium",
  timeStyle: "short",
});

/** الوقت الكامل لا النسبي: سجل التدقيق يُقرأ للمطابقة لا للتصفّح. */
export function formatEventTime(value: string): string {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  const date = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? "—" : eventTime.format(date);
}

/** `YYYY-MM-DD` من حقل تاريخ، مقارنًا باليوم المحلي للحدث. */
export function toLocalDateKey(value: string): string {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  const date = new Date(hasZone ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "";
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}
