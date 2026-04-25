import type { ReactNode } from "react";

export function Card({ title, children, style }: { title?: string; children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ background: "var(--bg-surface)", borderRadius: 12, padding: 20, ...style }}>
      {title && <h3 style={{ margin: "0 0 12px", fontSize: 14, color: "var(--text-secondary)" }}>{title}</h3>}
      {children}
    </div>
  );
}
