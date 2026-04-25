const ranges = [
  { label: "1h", hours: 1 },
  { label: "6h", hours: 6 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
  { label: "30d", hours: 720 },
];

export function TimeRangeSelector({ value, onChange }: { value: number; onChange: (h: number) => void }) {
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {ranges.map((r) => (
        <button
          key={r.hours}
          onClick={() => onChange(r.hours)}
          style={{
            padding: "4px 12px",
            borderRadius: 6,
            border: "none",
            cursor: "pointer",
            background: value === r.hours ? "var(--accent)" : "var(--btn-bg)",
            color: value === r.hours ? "#fff" : "var(--btn-text)",
            fontSize: 13,
          }}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}
