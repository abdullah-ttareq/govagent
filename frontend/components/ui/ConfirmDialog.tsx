"use client";

import Alert from "@/components/ui/Alert";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";

/** تأكيد إجراء مدمّر داخل الواجهة، بزر تأكيد بنبرة الخطر. */
export default function ConfirmDialog({
  isOpen,
  title,
  message,
  confirmLabel = "تأكيد",
  isBusy = false,
  error,
  onConfirm,
  onCancel,
}: {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  isBusy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal isOpen={isOpen} onClose={isBusy ? () => {} : onCancel} title={title}>
      <p className="mt-3 text-sm leading-relaxed text-muted">{message}</p>

      {error && (
        <Alert tone="error" className="mt-4">
          {error}
        </Alert>
      )}

      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-start">
        <Button variant="secondary" onClick={onCancel} disabled={isBusy}>
          إلغاء
        </Button>
        <Button
          variant="danger"
          onClick={onConfirm}
          isLoading={isBusy}
          loadingLabel="جارٍ التنفيذ…"
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
