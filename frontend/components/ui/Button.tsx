import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  /** يعرض مؤشّر انتظار ويعطّل الزر — لحالة الإرسال. */
  isLoading?: boolean;
  /** نص بديل يُعرض أثناء الانتظار بدل نص الزر. */
  loadingLabel?: string;
  block?: boolean;
  children: ReactNode;
};

/**
 * زر موحّد لكل الواجهة. الأنماط في `globals.css` (`.gv-btn`) لا هنا، حتى
 * يبقى نظام التصميم في مكان واحد.
 */
export default function Button({
  variant = "primary",
  isLoading = false,
  loadingLabel,
  block = false,
  className = "",
  disabled,
  children,
  ...rest
}: ButtonProps) {
  const classes = [
    "gv-btn",
    `gv-btn--${variant}`,
    block ? "gv-btn--block" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      {...rest}
      className={classes}
      disabled={disabled || isLoading}
      aria-busy={isLoading || undefined}
    >
      {isLoading && <span className="gv-spinner" aria-hidden="true" />}
      <span>{isLoading ? (loadingLabel ?? children) : children}</span>
    </button>
  );
}
