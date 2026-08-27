"use client";

import { useEffect, useState } from "react";
import ConversationItem from "@/components/ConversationItem";
import SessionFooter from "@/components/SessionFooter";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import ErrorNotice from "@/components/ui/ErrorNotice";
import Input from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";
import { describeFailure, type Failure } from "@/lib/errors";
import { validateTitle, type Conversation } from "@/lib/conversations";

type SidebarProps = {
  conversations: Conversation[];
  activeId: number | null;
  isLoading: boolean;
  failure: Failure | null;
  /** حالة الدرج على الشاشات الصغيرة. مهملة على الشاشات المتوسطة فأعلى. */
  isOpen: boolean;
  onClose: () => void;
  onSelect: (id: number) => void;
  onCreate: () => void;
  onRename: (id: number, title: string) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onRetry: () => void;
};

export default function Sidebar({
  conversations,
  activeId,
  isLoading,
  failure,
  isOpen,
  onClose,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  onRetry,
}: SidebarProps) {
  const [renameTarget, setRenameTarget] = useState<Conversation | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [isRenaming, setIsRenaming] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Escape يغلق الدرج على الجوال كما يغلق أي طبقة عائمة.
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  function openRename(conversation: Conversation) {
    setRenameTarget(conversation);
    setRenameValue(conversation.title);
    setRenameError(null);
  }

  async function submitRename(event: React.FormEvent) {
    event.preventDefault();
    if (!renameTarget || isRenaming) return;

    const invalid = validateTitle(renameValue);
    if (invalid) {
      setRenameError(invalid);
      return;
    }

    setIsRenaming(true);
    try {
      await onRename(renameTarget.id, renameValue.trim());
      setRenameTarget(null);
    } catch (caught) {
      setRenameError(describeFailure(caught, "تعذّرت إعادة التسمية."));
    } finally {
      setIsRenaming(false);
    }
  }

  async function submitDelete() {
    if (!deleteTarget || isDeleting) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await onDelete(deleteTarget.id);
      setDeleteTarget(null);
    } catch (caught) {
      setDeleteError(describeFailure(caught, "تعذّر حذف المحادثة."));
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <>
      {/* خلفية الدرج على الجوال وحده. */}
      {isOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`gv-sidebar ${isOpen ? "gv-sidebar--open" : ""}`}
        aria-label="المحادثات"
      >
        <div className="flex items-start justify-between gap-2 border-b border-border-subtle p-4">
          <div className="min-w-0">
            <p className="text-lg font-bold text-brand">GovAgent</p>
            <p className="mt-1 text-xs text-muted">المساعد الذكي للموظف</p>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="gv-icon-btn md:hidden"
            aria-label="إغلاق قائمة المحادثات"
          >
            <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5">
              <path
                fill="currentColor"
                d="M5.3 4.2 10 8.9l4.7-4.7 1.1 1.1L11.1 10l4.7 4.7-1.1 1.1L10 11.1l-4.7 4.7-1.1-1.1L8.9 10 4.2 5.3z"
              />
            </svg>
          </button>
        </div>

        <div className="p-3">
          <Button block onClick={onCreate}>
            + محادثة جديدة
          </Button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 pb-3">
          {isLoading ? (
            <ul className="space-y-2" aria-label="جارٍ التحميل">
              {[0, 1, 2].map((index) => (
                <li key={index} className="gv-skeleton h-14" />
              ))}
            </ul>
          ) : failure ? (
            <ErrorNotice failure={failure} onRetry={onRetry} />
          ) : conversations.length === 0 ? (
            <p className="rounded-md border border-dashed border-border-strong p-4 text-center text-xs leading-relaxed text-muted">
              لا توجد محادثات بعد.
              <br />
              ابدأ محادثة جديدة أو اكتب رسالتك مباشرة.
            </p>
          ) : (
            <ul className="space-y-1">
              {conversations.map((conversation) => (
                <ConversationItem
                  key={conversation.id}
                  conversation={conversation}
                  isActive={conversation.id === activeId}
                  onSelect={() => onSelect(conversation.id)}
                  onRename={() => openRename(conversation)}
                  onDelete={() => {
                    setDeleteTarget(conversation);
                    setDeleteError(null);
                  }}
                />
              ))}
            </ul>
          )}
        </nav>

        <SessionFooter />
      </aside>

      <Modal
        isOpen={renameTarget !== null}
        onClose={() => !isRenaming && setRenameTarget(null)}
        title="إعادة تسمية المحادثة"
      >
        <form onSubmit={submitRename} noValidate className="mt-4">
          <Input
            label="العنوان الجديد"
            value={renameValue}
            disabled={isRenaming}
            error={renameError}
            maxLength={300}
            onChange={(event) => {
              setRenameValue(event.target.value);
              if (renameError) setRenameError(null);
            }}
          />

          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-start">
            <Button
              type="button"
              variant="secondary"
              disabled={isRenaming}
              onClick={() => setRenameTarget(null)}
            >
              إلغاء
            </Button>
            <Button type="submit" isLoading={isRenaming} loadingLabel="جارٍ الحفظ…">
              حفظ
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        isOpen={deleteTarget !== null}
        title="حذف المحادثة"
        message={`سيُحذف «${deleteTarget?.title ?? ""}» ورسائله نهائيًا، ولا يمكن التراجع.`}
        confirmLabel="حذف نهائيًا"
        isBusy={isDeleting}
        error={deleteError}
        onConfirm={submitDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  );
}
