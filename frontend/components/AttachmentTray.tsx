"use client";

import { formatFileSize } from "@/lib/files";

/** ملف في الطابور: قبل الرفع، أو أثناءه، أو بعد فشله. */
export type Attachment = {
  /** معرّف محلّي — الملف لا معرّف له قبل أن يحفظه السيرفر. */
  id: string;
  file: File;
  status: "queued" | "uploading" | "done" | "failed";
  /** ٠ إلى ١٠٠ أثناء الرفع. */
  progress: number;
  /** سبب الفشل بالعربية، أو تحذير فهرسة بعد رفع ناجح. */
  error?: string | null;
  /** فهرسة لم تكتمل: الملف محفوظ لكنه لن يظهر في نتائج البحث. */
  warning?: string | null;
};

function StatusLine({ item }: { item: Attachment }) {
  if (item.status === "failed") {
    return <p className="gv-error-text mt-1">{item.error}</p>;
  }
  if (item.warning) {
    return <p className="mt-1 text-xs text-warning">{item.warning}</p>;
  }
  if (item.status === "done") {
    return <p className="mt-1 text-xs text-success">تم الرفع والفهرسة.</p>;
  }
  return <p className="mt-1 text-xs text-muted">{formatFileSize(item.file.size)}</p>;
}

/**
 * الملفات المُختارة قبل الإرسال ومعها تقدّمها.
 *
 * الإزالة متاحة في كل الحالات: قبل الرفع تسحب الملف من الطابور، وأثناءه
 * تلغيه فعلًا (`AbortSignal` في `lib/files.ts`)، وبعده تخفيه من العرض —
 * الملف يبقى محفوظًا على السيرفر، وحذفه من هناك مسار آخر.
 */
export default function AttachmentTray({
  items,
  onRemove,
}: {
  items: Attachment[];
  onRemove: (id: string) => void;
}) {
  if (items.length === 0) return null;

  return (
    <ul className="mb-3 space-y-2" aria-label="الملفات المرفقة">
      {items.map((item) => (
        <li key={item.id} className="gv-attachment">
          <div className="min-w-0 flex-1">
            <p
              className="gv-ltr-text truncate text-sm font-semibold"
              title={item.file.name}
            >
              {item.file.name}
            </p>

            <StatusLine item={item} />

            {item.status === "uploading" && (
              <div
                className="gv-progress mt-2"
                role="progressbar"
                aria-valuenow={item.progress}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`تقدّم رفع ${item.file.name}`}
              >
                <div
                  className="gv-progress__bar"
                  style={{ inlineSize: `${item.progress}%` }}
                />
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => onRemove(item.id)}
            className="gv-icon-btn gv-icon-btn--danger shrink-0"
            aria-label={
              item.status === "uploading"
                ? `إلغاء رفع ${item.file.name}`
                : `إزالة ${item.file.name}`
            }
          >
            <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4">
              <path
                fill="currentColor"
                d="M5.3 4.2 10 8.9l4.7-4.7 1.1 1.1L11.1 10l4.7 4.7-1.1 1.1L10 11.1l-4.7 4.7-1.1-1.1L8.9 10 4.2 5.3z"
              />
            </svg>
          </button>
        </li>
      ))}
    </ul>
  );
}
