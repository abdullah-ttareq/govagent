/**
 * رفع الملفات — `POST /api/files` الموجود فعلًا في
 * `backend/app/api/files.py`.
 *
 * الرفع بـ`XMLHttpRequest` لا بـ`fetch` **لسبب واحد**: `fetch` لا يعطي تقدّم
 * الرفع. `ReadableStream` في جسم الطلب ما زال محدود الدعم ويستلزم HTTP/2،
 * و`xhr.upload.onprogress` مدعوم في كل متصفح يعنينا. بقية الطلبات تبقى على
 * `apiRequest` في `lib/api.ts`.
 */

import { ApiError, NetworkError, type ApiErrorPayload } from "@/lib/api";
import { getServerUrl } from "@/lib/server-url";

/** يطابق `SUPPORTED_EXTENSIONS` في `backend/app/services/text_extraction.py`. */
export const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".txt"] as const;

/** يطابق `upload_max_bytes` في `backend/app/core/config.py` (١٠ ميجابايت). */
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

/** قيمة `accept` لحقل اختيار الملف. */
export const ACCEPT_ATTRIBUTE = SUPPORTED_EXTENSIONS.join(",");

/** يطابق `FileOut` في `backend/app/schemas/workspace.py`. */
export type StoredFile = {
  id: number;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  status: "pending" | "processed" | "failed";
  uploaded_by: number;
  can_modify: boolean;
  conversation_id: number | null;
  created_at: string;
};

/** يطابق `FileUploadResponse`. */
export type UploadResult = {
  file: StoredFile;
  chunk_count: number;
  indexing_error: string | null;
};

/** «٢٫٤ ميجابايت» — بالأرقام العربية وبفاصلة عشرية واحدة. */
export function formatFileSize(bytes: number): string {
  const units: [number, string][] = [
    [1024 * 1024, "ميجابايت"],
    [1024, "كيلوبايت"],
  ];

  for (const [factor, unit] of units) {
    if (bytes >= factor) {
      const value = bytes / factor;
      // منزلة عشرية واحدة تحت ١٠، وبلا كسور فوقها: «٩٫٤» مفيدة و«٩٤٫٣» لا.
      const text = value.toLocaleString("ar", {
        maximumFractionDigits: value < 10 ? 1 : 0,
      });
      return `${text} ${unit}`;
    }
  }

  return `${bytes.toLocaleString("ar")} بايت`;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

/**
 * تحقق في الواجهة قبل الإرسال — يوفّر على الموظف رفع عشرة ميجابايت ليُرفض،
 * ولا يحلّ محلّ تحقق السيرفر: نفس الفحوص هناك، وهي الحاجز الحقيقي.
 */
export function validateFile(file: File): string | null {
  const extension = extensionOf(file.name);
  const supported = SUPPORTED_EXTENSIONS.join("، ");

  if (!extension) {
    return `الملف «${file.name}» بلا امتداد، فتعذّر تحديد نوعه. الصيغ المدعومة: ${supported}.`;
  }
  if (!SUPPORTED_EXTENSIONS.includes(extension as (typeof SUPPORTED_EXTENSIONS)[number])) {
    return `صيغة «${extension}» غير مدعومة. الصيغ المدعومة: ${supported}.`;
  }
  if (file.size === 0) {
    return `الملف «${file.name}» فارغ، فلا محتوى فيه ليُفهرَس.`;
  }
  if (file.size > MAX_FILE_BYTES) {
    return (
      `حجم «${file.name}» ${formatFileSize(file.size)}، والحد الأقصى ` +
      `${formatFileSize(MAX_FILE_BYTES)}. قسّم الملف أو اضغطه ثم أعد رفعه.`
    );
  }
  return null;
}

/**
 * يرفع ملفًا ويبلّغ التقدّم من ٠ إلى ١٠٠.
 *
 * `conversationId` اختياري: الملف يُفهرَس لجهة الموظف في الحالتين، والربط
 * بمحادثة تفصيل عرض. `signal` يلغي الرفع فعليًا لا في الواجهة وحدها.
 */
export function uploadFile({
  token,
  file,
  conversationId,
  onProgress,
  signal,
}: {
  token: string;
  file: File;
  conversationId?: number | null;
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
}): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("تم إلغاء الرفع", "AbortError"));
      return;
    }

    const form = new FormData();
    form.append("file", file);
    if (conversationId) form.append("conversation_id", String(conversationId));

    const request = new XMLHttpRequest();
    request.open("POST", `${getServerUrl()}/api/files`);
    request.setRequestHeader("Authorization", `Bearer ${token}`);
    // لا Content-Type يدويًا: المتصفح يضيفه مع حدّ الأجزاء (boundary).

    request.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      onProgress?.(Math.round((event.loaded / event.total) * 100));
    };

    request.onload = () => {
      let payload: unknown = null;
      try {
        payload = JSON.parse(request.responseText);
      } catch {
        payload = null;
      }

      if (request.status >= 200 && request.status < 300) {
        onProgress?.(100);
        resolve(payload as UploadResult);
        return;
      }

      const error = (payload ?? {}) as ApiErrorPayload;
      reject(
        new ApiError(
          error.detail?.trim() || "تعذّر رفع الملف. حاول مرة أخرى.",
          request.status,
          error.code ?? "unknown_error",
        ),
      );
    };

    request.onerror = () => reject(new NetworkError());
    request.ontimeout = () => reject(new NetworkError());
    request.onabort = () =>
      reject(new DOMException("تم إلغاء الرفع", "AbortError"));

    signal?.addEventListener("abort", () => request.abort(), { once: true });

    request.send(form);
  });
}
