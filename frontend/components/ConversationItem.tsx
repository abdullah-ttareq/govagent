"use client";

import { formatRelativeTime } from "@/lib/format";
import type { Conversation } from "@/lib/conversations";

/** قلم — إعادة التسمية. */
function PencilIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4">
      <path
        fill="currentColor"
        d="M13.6 2.7a1.7 1.7 0 0 1 2.4 0l1.3 1.3a1.7 1.7 0 0 1 0 2.4l-8.5 8.5-3.9.9.9-3.9zM4 16.5h12a.75.75 0 0 1 0 1.5H4a.75.75 0 0 1 0-1.5"
      />
    </svg>
  );
}

/** سلة — الحذف. */
function TrashIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4">
      <path
        fill="currentColor"
        d="M8 2.5h4a1 1 0 0 1 1 1V4h3.25a.75.75 0 0 1 0 1.5h-.6l-.7 10a2 2 0 0 1-2 1.87H7.05a2 2 0 0 1-2-1.87l-.7-10h-.6a.75.75 0 0 1 0-1.5H7v-.5a1 1 0 0 1 1-1m.5 4.75a.75.75 0 0 0-1.5.05l.25 6a.75.75 0 0 0 1.5-.06zm4.5.05a.75.75 0 0 0-1.5-.05l-.25 6a.75.75 0 0 0 1.5.06z"
      />
    </svg>
  );
}

/**
 * صفّ محادثة واحد في الشريط الجانبي.
 *
 * الصفّ زر اختيار، وبجانبه زرّا التسمية والحذف. **الأزرار متجاورة لا
 * متداخلة**: زر داخل زر HTML غير صالح ولا ينقر عليه بلوحة المفاتيح.
 */
export default function ConversationItem({
  conversation,
  isActive,
  onSelect,
  onRename,
  onDelete,
}: {
  conversation: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  return (
    <li
      className={`gv-conversation ${isActive ? "gv-conversation--active" : ""}`}
    >
      <button
        type="button"
        onClick={onSelect}
        // aria-current ينطق «الحالي» لقارئ الشاشة؛ اللون وحده لا يكفي.
        aria-current={isActive ? "true" : undefined}
        className="min-w-0 flex-1 text-start"
      >
        <span className="block truncate text-sm font-medium">
          {conversation.title}
        </span>
        <span className="block text-xs text-muted">
          {formatRelativeTime(conversation.updated_at)}
          {conversation.message_count > 0 &&
            ` · ${conversation.message_count} رسالة`}
        </span>
      </button>

      <span className="gv-conversation__actions">
        <button
          type="button"
          onClick={onRename}
          className="gv-icon-btn"
          title="إعادة التسمية"
          aria-label={`إعادة تسمية المحادثة: ${conversation.title}`}
        >
          <PencilIcon />
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="gv-icon-btn gv-icon-btn--danger"
          title="حذف"
          aria-label={`حذف المحادثة: ${conversation.title}`}
        >
          <TrashIcon />
        </button>
      </span>
    </li>
  );
}
