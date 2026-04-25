export function Loading() {
  return <div style={{ padding: 40, textAlign: "center", color: "var(--text-secondary)" }}>Loading…</div>;
}

export function ErrorMsg({ msg }: { msg: string }) {
  return <div style={{ padding: 20, color: "#ef4444", background: "var(--error-bg)", borderRadius: 8 }}>Error: {msg}</div>;
}
