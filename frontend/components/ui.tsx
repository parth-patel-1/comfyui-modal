"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

/* Button — variants defined once per design-system state table */
export function Button({
  variant = "primary",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "outline" | "danger";
}) {
  const base =
    "gs-focus inline-flex items-center justify-center gap-2 rounded-lg px-4 h-10 " +
    "text-sm font-medium transition-colors disabled:opacity-45 disabled:cursor-not-allowed";
  const styles = {
    primary: "gs-gradient-btn text-white shadow-sm",
    ghost: "text-muted hover:text-fg hover:bg-surface-2",
    outline:
      "border border-line-strong text-fg hover:bg-surface-2 hover:border-accent-line",
    danger: "border border-danger/40 text-danger hover:bg-danger/10",
  }[variant];
  return (
    <button className={`${base} ${styles} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={
        "gs-focus w-full h-10 rounded-lg bg-surface-2 border border-line " +
        "px-3 text-sm text-fg placeholder:text-faint " +
        "focus:border-accent-line " +
        (props.className ?? "")
      }
    />
  );
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={
        "gs-focus w-full resize-none rounded-lg bg-transparent text-sm text-fg " +
        "placeholder:text-faint " +
        (props.className ?? "")
      }
    />
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-line bg-surface ${className}`}>
      {children}
    </div>
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "accent" | "success" | "danger" | "warning" | "info";
  children: ReactNode;
}) {
  const tones = {
    neutral: "bg-surface-2 text-muted border-line",
    accent: "bg-accent-soft text-accent border-accent-line",
    success: "bg-success/10 text-success border-success/30",
    danger: "bg-danger/10 text-danger border-danger/30",
    warning: "bg-warning/10 text-warning border-warning/30",
    info: "bg-info/10 text-info border-info/30",
  }[tone];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium ${tones}`}
    >
      {children}
    </span>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-muted">{label}</span>
      {children}
      {hint ? <span className="block text-[11px] text-faint">{hint}</span> : null}
    </label>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="text-xs text-danger bg-danger/10 border border-danger/25 rounded-lg px-3 py-2">
      {children}
    </p>
  );
}
