import { useFetch } from "../hooks/useFetch";
import { Card } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { Loading, ErrorMsg } from "../components/Feedback";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";

interface ResourceGroup {
  total: number;
  byStatus: Record<string, number>;
  items: Record<string, unknown>[];
}
type HealthData = Record<string, ResourceGroup>;

const statusColors: Record<string, string> = {
  ACTIVE: "#10b981", READY: "#10b981", CREATING: "#f59e0b", UPDATING: "#f59e0b",
  FAILED: "#ef4444", DELETING: "#6b7280", UNKNOWN: "#475569",
};

const sectionMeta: Record<string, { label: string; icon: string }> = {
  runtimes: { label: "Agent Runtimes", icon: "bi-cpu" },
  endpoints: { label: "Endpoints", icon: "bi-link-45deg" },
  gateways: { label: "Gateways", icon: "bi-signpost-split" },
  memories: { label: "Memories", icon: "bi-database" },
  codeInterpreters: { label: "Code Interpreters", icon: "bi-terminal" },
  browsers: { label: "Browsers", icon: "bi-globe2" },
};

function HealthCard({ name, group }: { name: string; group: ResourceGroup }) {
  const pieData = Object.entries(group.byStatus).map(([status, count]) => ({ name: status, value: count }));
  const activeCount = (group.byStatus.ACTIVE || 0) + (group.byStatus.READY || 0);
  const healthPct = group.total > 0 ? Math.round((activeCount / group.total) * 100) : 0;
  const meta = sectionMeta[name];

  return (
    <Card style={{ flex: "1 1 260px", minWidth: 260 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ width: 80, height: 80 }}>
          {pieData.length > 0 ? (
            <ResponsiveContainer>
              <PieChart>
                <Pie data={pieData} innerRadius={26} outerRadius={38} dataKey="value" stroke="none">
                  {pieData.map((d, i) => <Cell key={i} fill={statusColors[d.name] || "#475569"} />)}
                </Pie>
                <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ width: 80, height: 80, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>—</div>
          )}
        </div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
            <i className={`bi ${meta?.icon || "bi-box"}`} style={{ fontSize: 14 }} />
            {meta?.label || name}
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: healthPct >= 80 ? "#10b981" : healthPct >= 50 ? "#f59e0b" : "#ef4444" }}>
            {healthPct}%
          </div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{group.total} total</div>
        </div>
      </div>
    </Card>
  );
}

function getName(item: Record<string, unknown>): string {
  // For endpoints, prepend the agent runtime name
  if (item.agentRuntimeArn && item.name) {
    const arn = String(item.agentRuntimeArn);
    const runtimeId = arn.split("/").pop() || "";
    const agentName = runtimeId.replace(/-[a-zA-Z0-9]{10}$/, "");
    return `${agentName}::${item.name}`;
  }
  return (item.name || item.agentRuntimeName || item.gatewayName
    || item.id || item.memoryId || item.agentRuntimeId || item.gatewayId
    || item.codeInterpreterId || item.browserId || "—") as string;
}

function getCreated(item: Record<string, unknown>): string {
  const raw = item.createdAt ?? item.lastUpdatedAt ?? item.createdTime ?? "";
  if (!raw) return "—";
  const d = typeof raw === "number" ? new Date(raw * 1000) : new Date(raw as string);
  return isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

function ResourceTable({ name, group }: { name: string; group: ResourceGroup }) {
  if (group.items.length === 0) return null;
  const meta = sectionMeta[name];

  return (
    <Card title={meta?.label || name} style={{ marginBottom: 16 }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
            <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 12 }}>NAME / ID</th>
            <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 12 }}>STATUS</th>
            <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 12 }}>CREATED</th>
          </tr>
        </thead>
        <tbody>
          {group.items.map((item, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--border-row)" }}>
              <td style={{ padding: 10, fontSize: 14 }}>{getName(item)}</td>
              <td style={{ padding: 10 }}><StatusBadge status={(item.status || "UNKNOWN") as string} /></td>
              <td style={{ padding: 10, fontSize: 13, color: "var(--text-secondary)" }}>{getCreated(item)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

export default function InventoryPage() {
  const { data, loading, error, refetch } = useFetch<HealthData>("/api/health/overview");

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, margin: 0 }}>Agent Inventory</h1>
        <button onClick={refetch} style={{ padding: "6px 16px", borderRadius: 6, border: "none", background: "var(--btn-bg)", color: "var(--btn-text)", cursor: "pointer" }}>
          <i className="bi bi-arrow-clockwise" style={{ marginRight: 6 }} />Refresh
        </button>
      </div>

      {loading && <Loading />}
      {error && <ErrorMsg msg={error} />}

      {data && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginBottom: 24 }}>
            {Object.entries(data).map(([name, group]) => (
              <HealthCard key={name} name={name} group={group} />
            ))}
          </div>

          {Object.entries(data).map(([name, group]) => (
            <ResourceTable key={name} name={name} group={group} />
          ))}
        </>
      )}
    </div>
  );
}
