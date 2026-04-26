import { useState } from "react";
import { useFetch } from "../hooks/useFetch";
import { Card } from "../components/Card";
import { TimeRangeSelector } from "../components/TimeRangeSelector";
import { StatusBadge } from "../components/StatusBadge";
import { Loading, ErrorMsg } from "../components/Feedback";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  AreaChart, Area, PieChart, Pie, Cell, Legend,
} from "recharts";

interface Summary {
  total_invocations: number;
  total_sessions: number;
  total_errors: number;
  total_throttles: number;
  avg_latency_ms: number;
  error_rate_pct: number;
  total_cpu_vcpu_hours: number;
  total_mem_gb_hours: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  bedrock_invocations: number;
  avg_model_latency_ms: number;
  avg_ttft_ms: number;
  p90_ttft_ms: number;
  cost_total_usd: number;
  cost_by_service: Record<string, number>;
}

interface AgentMetrics {
  name: string; arn: string; agentRuntimeId: string; status: string;
  Invocations: number; Latency: number; SystemErrors: number; UserErrors: number;
  TotalErrors: number; ErrorRate: number; Sessions: number; Throttles: number;
  "CPUUsed-vCPUHours": number; "MemoryUsed-GBHours": number;
  EstimatedCost: number; ComputeCost: number; CpuCost: number; MemCost: number;
  InputTokens: number; OutputTokens: number; TotalTokens: number;
}

interface TimelineSeries { timestamps: string[]; values: number[]; total: number }

interface CostDay { date: string; total: number; bedrock: number; agentcore: number }

interface ModelMetrics {
  modelId: string; name: string;
  Invocations: number; InputTokenCount: number; OutputTokenCount: number;
  TotalTokens: number; InvocationLatency: number; TimeToFirstToken: number;
  TotalErrors: number;
}

interface EvalConfig {
  onlineEvaluationConfigId?: string;
  onlineEvaluationConfigName?: string;
  name?: string;
  status?: string;
  executionStatus?: string;
  description?: string;
}

interface DashboardData {
  summary: Summary;
  resource_counts: Record<string, number>;
  status_distribution: Record<string, Record<string, number>>;
  agents: AgentMetrics[];
  models: ModelMetrics[];
  model_latency: Record<string, { ttft?: { timestamps: string[]; values: number[] }; latency?: { timestamps: string[]; values: number[] } }>;
  has_agentcore_metrics: boolean;
  has_span_tokens: boolean;
  eval_configs: EvalConfig[];
  timeline: Record<string, TimelineSeries>;
  tokens: Record<string, TimelineSeries>;
  cost: { daily: CostDay[]; total: number; currency?: string; error?: string };
  agentcore_breakdown: { categories: Record<string, number>; daily: Record<string, string | number>[] };
}

const barColors = ["#818cf8", "#34d399", "#f472b6", "#fbbf24", "#60a5fa", "#a78bfa", "#fb923c", "#22d3ee"];

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n % 1 === 0 ? n.toFixed(0) : n.toFixed(1);
}

function fmtUsd(n: number): string {
  return `$${n.toFixed(2)}`;
}

function KpiCard({ icon, label, value, sub, color }: { icon: string; label: string; value: string; sub?: string; color?: string }) {
  return (
    <Card style={{ flex: "1 1 170px", minWidth: 170 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: "var(--accent-bg)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <i className={`bi ${icon}`} style={{ fontSize: 18, color: color || "var(--accent-text)" }} />
        </div>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, color: color || "var(--text-primary)", lineHeight: 1.1 }}>{value}</div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>{label}</div>
          {sub && <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{sub}</div>}
        </div>
      </div>
    </Card>
  );
}

function ResourcePill({ icon, label, count }: { icon: string; label: string; count: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", background: "var(--bg-surface-alt)", borderRadius: 8 }}>
      <i className={`bi ${icon}`} style={{ fontSize: 14, color: "var(--accent-text)" }} />
      <span style={{ fontSize: 13 }}>{label}</span>
      <span style={{ marginLeft: "auto", fontWeight: 700, fontSize: 15 }}>{count}</span>
    </div>
  );
}

export default function DashboardPage() {
  const [hours, setHours] = useState(24);
  const { data, loading, error } = useFetch<DashboardData>(`/api/dashboard?hours=${hours}`);

  const s = data?.summary;
  const agents = data?.agents ?? [];
  const tokens = data?.tokens ?? {};
  const cost = data?.cost;
  const rc = data?.resource_counts ?? {};
  const evalConfigs = data?.eval_configs ?? [];
  const models = data?.models ?? [];
  const modelLatency = data?.model_latency ?? {};
  const acBreakdown = data?.agentcore_breakdown;

  // Per-model TTFT and Latency — separate clean timelines
  const modelNames = Object.keys(modelLatency);
  const ttftChartData: Record<string, string | number>[] = [];
  const latencyChartData: Record<string, string | number>[] = [];

  // Build TTFT chart data
  const ttftTimestamps = new Set<string>();
  for (const mn of modelNames) {
    for (const ts of modelLatency[mn]?.ttft?.timestamps ?? []) ttftTimestamps.add(ts);
  }
  for (const t of [...ttftTimestamps].sort()) {
    const row: Record<string, string | number> = {
      time: new Date(t).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    };
    for (const mn of modelNames) {
      const data = modelLatency[mn]?.ttft;
      const idx = data?.timestamps?.indexOf(t) ?? -1;
      row[mn] = idx >= 0 ? Math.round(data!.values[idx]) : 0;
    }
    ttftChartData.push(row);
  }

  // Build Latency chart data
  const latTimestamps = new Set<string>();
  for (const mn of modelNames) {
    for (const ts of modelLatency[mn]?.latency?.timestamps ?? []) latTimestamps.add(ts);
  }
  for (const t of [...latTimestamps].sort()) {
    const row: Record<string, string | number> = {
      time: new Date(t).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    };
    for (const mn of modelNames) {
      const data = modelLatency[mn]?.latency;
      const idx = data?.timestamps?.indexOf(t) ?? -1;
      row[mn] = idx >= 0 ? Math.round(data!.values[idx]) : 0;
    }
    latencyChartData.push(row);
  }

  const modelColors = ["#818cf8", "#34d399", "#f472b6", "#fbbf24", "#60a5fa"];

  // Token timeline
  const tokenTimeline = (tokens.input_tokens?.timestamps ?? []).map((t, i) => ({
    time: new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    input: tokens.input_tokens?.values[i] ?? 0,
    output: tokens.output_tokens?.values[i] ?? 0,
  }));

  // Cost chart with service breakdown
  const costChart = (cost?.daily ?? []).map((d) => ({
    date: d.date.slice(5),
    bedrock: d.bedrock ?? 0,
    agentcore: d.agentcore ?? 0,
  }));

  // Per-agent estimated cost
  const agentCostData = agents
    .filter((a) => a.ComputeCost > 0)
    .map((a) => ({ name: a.name, cpu: a.CpuCost, memory: a.MemCost }));

  // Per-agent token data (actual from spans)
  const hasSpanTokens = data?.has_span_tokens ?? false;
  const agentTokenData = agents
    .filter((a) => a.TotalTokens > 0)
    .map((a) => ({ name: a.name, input: a.InputTokens, output: a.OutputTokens }));

  // Per-model data
  const modelTokenData = models
    .filter((m) => m.TotalTokens > 0)
    .map((m) => ({ name: m.name, input: m.InputTokenCount, output: m.OutputTokenCount }));

  const modelInvData = models
    .filter((m) => m.Invocations > 0)
    .map((m) => ({ name: m.name, invocations: m.Invocations }));

  // AgentCore cost breakdown
  const acCategories = acBreakdown?.categories ?? {};
  const acCatData = Object.entries(acCategories).map(([name, value]) => ({ name, value }));
  const acDailyData = (acBreakdown?.daily ?? []).map((d) => ({
    ...d,
    date: String(d.date).slice(5),
  }));
  const acCatNames = Object.keys(acCategories);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 24, margin: 0 }}>AgentLook</h1>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: "4px 0 0" }}>Single pane of glass for all your agents</p>
        </div>
        <TimeRangeSelector value={hours} onChange={setHours} />
      </div>

      {loading && <Loading />}
      {error && <ErrorMsg msg={error} />}

      {s && (
        <>
          {/* ── KPI Row ── */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 20 }}>
            <KpiCard icon="bi-lightning-charge-fill" label="Invocations" value={fmt(s.total_invocations)} />
            <KpiCard icon="bi-people-fill" label="Sessions" value={fmt(s.total_sessions)} />
            <KpiCard icon="bi-clock-history" label="Avg Agent Latency" value={`${Math.round(s.avg_latency_ms)}ms`} sub="avg across agents" color="#fbbf24" />
            <KpiCard icon="bi-skip-forward-fill" label="Avg TTFT (Model)" value={`${Math.round(s.avg_ttft_ms)}ms`} sub={`p90: ${Math.round(s.p90_ttft_ms)}ms`} color="#f472b6" />
            <KpiCard icon="bi-exclamation-triangle-fill" label="Error Rate" value={`${s.error_rate_pct}%`} sub={`${fmt(s.total_errors)} errors`} color={s.error_rate_pct > 5 ? "#ef4444" : "#10b981"} />
            <KpiCard icon="bi-coin" label="Tokens" value={fmt(s.total_tokens)} sub={`In: ${fmt(s.input_tokens)} / Out: ${fmt(s.output_tokens)}`} color="#818cf8" />
            <KpiCard icon="bi-currency-dollar" label="Cost" value={fmtUsd(s.cost_total_usd)} color="#34d399" />
          </div>

          {/* ── Resource counts + Cost by Service ── */}
          <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
            <Card title="Resource Inventory" style={{ flex: 2 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <ResourcePill icon="bi-cpu" label="Runtimes" count={rc.runtimes ?? 0} />
                <ResourcePill icon="bi-link-45deg" label="Endpoints" count={rc.endpoints ?? 0} />
                <ResourcePill icon="bi-signpost-split" label="Gateways" count={rc.gateways ?? 0} />
                <ResourcePill icon="bi-bullseye" label="Gateway Targets" count={rc.gateway_targets ?? 0} />
                <ResourcePill icon="bi-database" label="Memories" count={rc.memories ?? 0} />
                <ResourcePill icon="bi-check2-circle" label="Eval Configs" count={rc.eval_configs ?? 0} />
                <ResourcePill icon="bi-terminal" label="Code Interpreters" count={rc.code_interpreters ?? 0} />
                <ResourcePill icon="bi-globe2" label="Browsers" count={rc.browsers ?? 0} />
              </div>
            </Card>

            <Card title="Cost by Service" style={{ flex: 1, minWidth: 240 }}>
              {Object.keys(s.cost_by_service ?? {}).length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={150}>
                    <PieChart>
                      <Pie
                        data={Object.entries(s.cost_by_service).map(([name, value]) => ({ name: name.replace("Amazon ", ""), value }))}
                        innerRadius={35} outerRadius={55} dataKey="value" stroke="none"
                      >
                        <Cell fill="#818cf8" />
                        <Cell fill="#34d399" />
                      </Pie>
                      <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                        formatter={(v) => [`$${Number(v).toFixed(4)}`, ""]} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                    {Object.entries(s.cost_by_service).map(([svc, amt], i) => (
                      <div key={svc} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                        <div style={{ width: 10, height: 10, borderRadius: 2, background: i === 0 ? "#818cf8" : "#34d399" }} />
                        <span style={{ color: "var(--text-secondary)" }}>{svc.replace("Amazon ", "")}</span>
                        <span style={{ marginLeft: "auto", fontWeight: 600 }}>${amt.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 20 }}>No cost data</div>
              )}
            </Card>
          </div>

          {/* ── TTFT & Latency by Model (separate charts) ── */}
          <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
            <Card title="Time to First Token (TTFT) by Model" style={{ flex: 1 }}>
              {ttftChartData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={ttftChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                    <XAxis dataKey="time" tick={{ fontSize: 9, fill: "var(--text-muted)" }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} unit="ms" />
                    <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                      formatter={(v) => [v + "ms", ""]} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    {modelNames.map((mn, i) => (
                      <Area key={mn} type="monotone" dataKey={mn} stroke={modelColors[i % modelColors.length]} fill={modelColors[i % modelColors.length]} fillOpacity={0.08} strokeWidth={2} dot={false} />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 20 }}>No TTFT data — requires streaming API usage</div>
              )}
            </Card>

            <Card title="Model Invocation Latency" style={{ flex: 1 }}>
              {latencyChartData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={latencyChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                    <XAxis dataKey="time" tick={{ fontSize: 9, fill: "var(--text-muted)" }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} unit="ms" />
                    <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                      formatter={(v) => [v + "ms", ""]} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    {modelNames.map((mn, i) => (
                      <Area key={mn} type="monotone" dataKey={mn} stroke={modelColors[i % modelColors.length]} fill={modelColors[i % modelColors.length]} fillOpacity={0.08} strokeWidth={2} dot={false} />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 20 }}>No latency data</div>
              )}
            </Card>
          </div>

          {/* ── Agent Leaderboard ── */}
          <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
            <Card title="Agent Leaderboard — Invocations" style={{ flex: 1 }}>
              {agents.length > 0 ? (
                <ResponsiveContainer width="100%" height={Math.max(agents.length * 40, 100)}>
                  <BarChart data={agents} layout="vertical" margin={{ left: 10, right: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                    <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 11, fill: "var(--text-secondary)" }} />
                    <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                    <Bar dataKey="Invocations" radius={[0, 4, 4, 0]}>
                      {agents.map((_, i) => <Cell key={i} fill={barColors[i % barColors.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 20 }}>No agent data</div>
              )}
            </Card>
          </div>

          {/* -- Per-model metrics -- */}
          {models.length > 0 && (
            <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
              <Card title="Token Usage by Model" style={{ flex: 1 }}>
                {modelTokenData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={Math.max(modelTokenData.length * 44, 100)}>
                    <BarChart data={modelTokenData} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                      <YAxis type="category" dataKey="name" width={180} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                      <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar dataKey="input" name="Input" stackId="tok" fill="#818cf8" />
                      <Bar dataKey="output" name="Output" stackId="tok" fill="#34d399" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 20 }}>No token data</div>
                )}
              </Card>

              <Card title="Invocations by Model" style={{ flex: 1 }}>
                {modelInvData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={Math.max(modelInvData.length * 44, 100)}>
                    <BarChart data={modelInvData} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                      <YAxis type="category" dataKey="name" width={180} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                      <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                      <Bar dataKey="invocations" radius={[0, 4, 4, 0]}>
                        {modelInvData.map((_, i) => <Cell key={i} fill={barColors[i % barColors.length]} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 20 }}>No invocation data</div>
                )}
              </Card>
            </div>
          )}

          {/* -- Model Detail Table -- */}
          {models.length > 0 && (
            <Card title="Model Details" style={{ marginBottom: 20 }}>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11 }}>MODEL</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>INVOCATIONS</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>INPUT TOKENS</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>OUTPUT TOKENS</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>LATENCY (ms)</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>TTFT (ms)</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>ERRORS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.map((m, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid var(--border-row)" }}>
                        <td style={{ padding: 10, fontSize: 13 }}>{m.name}</td>
                        <td style={{ padding: 10, textAlign: "right", fontWeight: 600 }}>{fmt(m.Invocations)}</td>
                        <td style={{ padding: 10, textAlign: "right", color: "#818cf8" }}>{fmt(m.InputTokenCount)}</td>
                        <td style={{ padding: 10, textAlign: "right", color: "#34d399" }}>{fmt(m.OutputTokenCount)}</td>
                        <td style={{ padding: 10, textAlign: "right" }}>{m.InvocationLatency}ms</td>
                        <td style={{ padding: 10, textAlign: "right", color: "#f472b6" }}>{m.TimeToFirstToken}ms</td>
                        <td style={{ padding: 10, textAlign: "right", color: m.TotalErrors > 0 ? "#ef4444" : "inherit" }}>{fmt(m.TotalErrors)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {/* -- Token usage + Cost -- */}
          <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
            <Card title="Token Usage Over Time" style={{ flex: 1 }}>
              {tokenTimeline.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={tokenTimeline}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                    <XAxis dataKey="time" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                    <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                    <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                    <Area type="monotone" dataKey="input" name="Input Tokens" stroke="#818cf8" fill="#818cf8" fillOpacity={0.15} />
                    <Area type="monotone" dataKey="output" name="Output Tokens" stroke="#34d399" fill="#34d399" fillOpacity={0.15} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 20 }}>No token data</div>
              )}
            </Card>

            <Card title="Daily Cost — Bedrock vs AgentCore" style={{ flex: 1 }}>
              {costChart.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={costChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                    <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                    <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                      formatter={(v) => ["$" + Number(v).toFixed(4), ""]} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="bedrock" name="Bedrock" stackId="cost" fill="#818cf8" />
                    <Bar dataKey="agentcore" name="AgentCore" stackId="cost" fill="#34d399" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 20 }}>
                  {cost?.error ? "Cost Explorer: " + cost.error : "No cost data"}
                </div>
              )}
            </Card>
          </div>

          {/* -- AgentCore Cost Breakdown -- */}
          {acCatData.length > 0 && (
            <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
              <Card title="AgentCore Cost Breakdown" style={{ flex: 1, minWidth: 280 }}>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie data={acCatData} innerRadius={45} outerRadius={75} dataKey="value" stroke="none"
                      label={({ name, percent }) => name + " " + ((percent ?? 0) * 100).toFixed(0) + "%"}>
                      {acCatData.map((_, i) => <Cell key={i} fill={["#818cf8", "#34d399", "#f472b6", "#fbbf24", "#60a5fa", "#fb923c"][i % 6]} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                      formatter={(v) => ["$" + Number(v).toFixed(4), ""]} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
                  {acCatData.map((c, i) => (
                    <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                      <div style={{ width: 10, height: 10, borderRadius: 2, background: ["#818cf8", "#34d399", "#f472b6", "#fbbf24", "#60a5fa", "#fb923c"][i % 6] }} />
                      <span style={{ color: "var(--text-secondary)" }}>{c.name}</span>
                      <span style={{ marginLeft: "auto", fontWeight: 600 }}>{"$" + c.value.toFixed(4)}</span>
                    </div>
                  ))}
                </div>
              </Card>

              <Card title="AgentCore Daily Cost by Category" style={{ flex: 2 }}>
                {acDailyData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={acDailyData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                      <XAxis dataKey="date" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                      <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                      <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                        formatter={(v) => ["$" + Number(v).toFixed(4), ""]} />
                      <Legend wrapperStyle={{ fontSize: 10 }} />
                      {acCatNames.map((cat, i) => (
                        <Bar key={cat} dataKey={cat} stackId="ac" fill={["#818cf8", "#34d399", "#f472b6", "#fbbf24", "#60a5fa", "#fb923c"][i % 6]}
                          radius={i === acCatNames.length - 1 ? [4, 4, 0, 0] : undefined} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 20 }}>No daily data</div>
                )}
              </Card>
            </div>
          )}

          {/* -- Per-agent cost + tokens -- */}
          {(agentCostData.length > 0 || agentTokenData.length > 0) && (
            <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
              {agentCostData.length > 0 && (
                <Card title="Compute Cost by Agent" style={{ flex: 1 }}>
                  <ResponsiveContainer width="100%" height={Math.max(agentCostData.length * 40, 100)}>
                    <BarChart data={agentCostData} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                      <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 11, fill: "var(--text-secondary)" }} />
                      <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                        formatter={(v) => ["$" + Number(v).toFixed(4), ""]} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar dataKey="cpu" name="CPU ($0.0895/vCPU·h)" stackId="cost" fill="#818cf8" />
                      <Bar dataKey="memory" name="Memory ($0.00945/GB·h)" stackId="cost" fill="#34d399" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </Card>
              )}
              {agentTokenData.length > 0 && (
                <Card title="Token Usage by Agent" style={{ flex: 1 }}>
                  <ResponsiveContainer width="100%" height={Math.max(agentTokenData.length * 40, 100)}>
                    <BarChart data={agentTokenData} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                      <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 11, fill: "var(--text-secondary)" }} />
                      <Tooltip contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar dataKey="input" name="Input" stackId="tok" fill="#818cf8" />
                      <Bar dataKey="output" name="Output" stackId="tok" fill="#34d399" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </Card>
              )}
            </div>
          )}

          {/* -- Agent Detail Table -- */}
          {agents.length > 0 && (
            <Card title="Agent Details">
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 900 }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11 }}>AGENT</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11 }}>STATUS</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>INVOCATIONS</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>SESSIONS</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>AVG LATENCY</th>
                      {hasSpanTokens && <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>IN TOKENS</th>}
                      {hasSpanTokens && <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>OUT TOKENS</th>}
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>ERRORS</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>ERR %</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>CPU (vCPU·h)</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>MEM (GB·h)</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11, textAlign: "right" }}>COMPUTE COST</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map((a, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid var(--border-row)" }}>
                        <td style={{ padding: 10 }}>
                          <div style={{ fontSize: 13, fontWeight: 600 }}>{a.name}</div>
                          <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{a.agentRuntimeId}</div>
                        </td>
                        <td style={{ padding: 10 }}><StatusBadge status={a.status} /></td>
                        <td style={{ padding: 10, textAlign: "right", fontWeight: 600 }}>{fmt(a.Invocations)}</td>
                        <td style={{ padding: 10, textAlign: "right" }}>{fmt(a.Sessions)}</td>
                        <td style={{ padding: 10, textAlign: "right" }}>{Math.round(a.Latency)}ms</td>
                        {hasSpanTokens && <td style={{ padding: 10, textAlign: "right", color: "#818cf8" }}>{fmt(a.InputTokens)}</td>}
                        {hasSpanTokens && <td style={{ padding: 10, textAlign: "right", color: "#34d399" }}>{fmt(a.OutputTokens)}</td>}
                        <td style={{ padding: 10, textAlign: "right", color: a.TotalErrors > 0 ? "#ef4444" : "inherit" }}>{fmt(a.TotalErrors)}</td>
                        <td style={{ padding: 10, textAlign: "right", color: a.ErrorRate > 5 ? "#ef4444" : "inherit" }}>{a.ErrorRate}%</td>
                        <td style={{ padding: 10, textAlign: "right" }}>{a["CPUUsed-vCPUHours"].toFixed(3)}</td>
                        <td style={{ padding: 10, textAlign: "right" }}>{a["MemoryUsed-GBHours"].toFixed(3)}</td>
                        <td style={{ padding: 10, textAlign: "right", color: "#34d399" }}>{"$" + a.ComputeCost.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {/* -- Evaluation Configs -- */}
          {evalConfigs.length > 0 && (
            <Card title="Online Evaluation Configs" style={{ marginTop: 20 }}>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11 }}>CONFIG NAME</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11 }}>ID</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11 }}>STATUS</th>
                      <th style={{ padding: 10, color: "var(--text-secondary)", fontSize: 11 }}>EXECUTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evalConfigs.map((c, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid var(--border-row)" }}>
                        <td style={{ padding: 10, fontSize: 13 }}>{c.onlineEvaluationConfigName || c.name || "—"}</td>
                        <td style={{ padding: 10, fontSize: 12, color: "var(--text-muted)" }}>{c.onlineEvaluationConfigId || "—"}</td>
                        <td style={{ padding: 10 }}><StatusBadge status={c.status || "UNKNOWN"} /></td>
                        <td style={{ padding: 10 }}><StatusBadge status={c.executionStatus || "—"} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
