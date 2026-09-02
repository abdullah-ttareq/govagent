"use client";

import { useId, type InputHTMLAttributes } from "react";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  /** رسالة خطأ عربية تُعرض تحت الحقل وتربط به عبر aria-describedby. */
  error?: string | null;
  hint?: string;
};

/**
 * حقل إدخال موحّد مع تسمية ورسالة خطأ مرتبطة به لقارئ الشاشة.
 *
 * الاتجاه يأتي من `dir="rtl"` على `<html>`، عدا حقل البريد فيمرَّر
 * `dir="ltr"` من مكان الاستدعاء: عنوان البريد لاتيني، وعرضه RTL يقلب موضع
 * النقطة و`@` بصريًا.
 */
export default function Input({
  label,
  error,
  hint,
  id,
  className = "",
  ...rest
}: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;

  const describedBy =
    [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ") ||
    undefined;

  return (
    <div className="gv-field">
      <label className="gv-label" htmlFor={inputId}>
        {label}
      </label>

      <input
        {...rest}
        id={inputId}
        className={`gv-input ${className}`.trim()}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
      />

      {hint && (
        <p className="gv-hint" id={hintId}>
          {hint}
        </p>
      )}

      {error && (
        <p className="gv-error-text" id={errorId}>
          {error}
        </p>
      )}
    </div>
  );
}
