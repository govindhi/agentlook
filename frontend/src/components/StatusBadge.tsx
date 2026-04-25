const colors: Record<string, string> = {
  ACTIVE: "#10b981",
  READY: "#10b981",
  CREATING: "#f59e0b",
  UPDATING: "#f59e0b",
  IN_PROGRESS: "#f59e0b",
  FAILED: "#ef4444",
  DELETING: "#6b7280",
  UNKNOWN: "#6b7280",
};

export function StatusBadge({ status }: { status: string }) {
  const bg = colors[status] || colors.UNKNOWN;
  return (
    <span
      style={{
        background: bg,
        color: "#fff",
        padding: "2px 10px",
        borderRadius: 12,
        fontSize: 12,
        fontWeight: 600,
      }}
    >
      {status}
    </span>
  );
}
