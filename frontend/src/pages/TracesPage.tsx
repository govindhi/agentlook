import { useState } from "react";
import { useFetch } from "../hooks/useFetch";
import { Card } from "../components/Card";
import { TimeRangeSelector } from "../components/TimeRangeSelector";
import { Loading, ErrorMsg } from "../components/Feedback";

interface Span {
  traceId?: string; spanId?: string; parentSpanId?: string; name?: string;
  operation?: string; agent_id?: string; session_id?: string;
  latency_ms?: string; error_type?: string; resource_arn?: string;
  duration?: string; "@timestamp"?: string; tool_name?: string;
  children?: Span[];
}

interface TraceSearchResponse {
  traces: Span[];
  otel_enabled: boolean;
  message?: string;
}

interface AgentRuntime {
  agentRuntimeId?: string;
  agentRuntimeName?: string;
  name?: string;
  status?: string;
  description?: string;
}

function WaterfallSpan({ span, depth = 0, maxDuration }: { span: Span; depth?: number; maxDuration: number }) {
  const dur = parseFloat(span.latency_ms || span.duration || "0");
  const pct = maxDuration > 0 ? (dur / maxDuration) * 100 : 0;
  const hasError = !!span.error_type;
  const color = hasError ? "#ef4444" : depth === 0 ? "#818cf8" : depth === 1 ? "#34d399" : "#fbbf24";

  return (
    <div style={{ marginLeft: depth * 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0" }}>
        <div style={{ width: 180, fontSize: 12, color: "var(--text-secondary)", flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {span.operation || span.name || span.spanId?.slice(0, 12)}
          {span.tool_name && <span style={{ color: "#fbbf24" }}> ({span.tool_name})</span>}
        </div>
        <div style={{ flex: 1, background: "var(--waterfall-bar)", borderRadius: 4, height: 20, position: "relative" }}>
          <div style={{ width: `${Math.max(pct, 2)}%`, background: color, borderRadius: 4, height: "100%", opacity: 0.8 }} />
          <span style={{ position: "absolute", right: 6, top: 2, fontSize: 11, color: "var(--waterfall-text)" }}>{dur.toFixed(0)}ms</span>
        </div>
        {hasError && <span style={{ fontSize: 11, color: "#ef4444" }}><i className="bi bi-exclamation-triangle" /> {span.error_type}</span>}
      </div>
      {span.children?.map((c, i) => (
        <WaterfallSpan key={i} span={c} depth={depth + 1} maxDuration={maxDuration} />
      ))}
    </div>
  );
}

export default function TracesPage() {
  const [hours, setHours] = useState(24);
  const [agentId, setAgentId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [errorOnly, setErrorOnly] = useState(false);
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null);

  const params = new URLSearchParams({ hours: String(hours) });
  if (agentId) params.set("agent_id", agentId);
  if (sessionId) params.set("session_id", sessionId);
  if (errorOnly) params.set("error_only", "true");

  const { data: searchResult, loading, error } = useFetch<TraceSearchResponse>(`/api/traces/search?${params}`);
  const { data: traceDetail } = useFetch<{ traceId: string; spans: Span[] }>(
    selectedTrace ? `/api/traces/${selectedTrace}` : null
  );
  const { data: runtimes } = useFetch<AgentRuntime[]>("/api/inventory/runtimes");

  const traces = searchResult?.traces ?? [];
  const otelEnabled = searchResult?.otel_enabled ?? true;

  const maxDuration = traceDetail?.spans
    ? Math.max(...traceDetail.spans.map((s) => parseFloat(s.latency_ms || s.duration || "0")), 1)
    : 1;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, margin: 0 }}>Trace Viewer</h1>
        <TimeRangeSelector value={hours} onChange={setHours} />
      </div>

      {!otelEnabled && (
        <div style={{
          background: "var(--otel-banner-bg)", border: "1px solid var(--border)", borderRadius: 8,
          padding: 20, marginBottom: 20,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <i className="bi bi-broadcast" style={{ fontSize: 18, color: "#fbbf24" }} />
            <span style={{ fontSize: 15, color: "#fbbf24" }}>No OTEL logs enabled</span>
          </div>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, margin: "0 0 16px 0" }}>
            The OTEL spans log group does not exist. Configure your agents to export traces to CloudWatch Logs to view them here.
          </p>

          {runtimes && runtimes.length > 0 && (
            <>
              <div style={{ fontSize: 13, color: "var(--text-primary)", marginBottom: 8 }}>
                Agent Runtimes ({runtimes.length}):
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {runtimes.map((rt) => (
                  <div key={rt.agentRuntimeId} style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "8px 12px", background: "var(--otel-item-bg)", borderRadius: 6,
                  }}>
                    <i className="bi bi-cpu" style={{ color: "var(--text-secondary)" }} />
                    <span style={{ fontSize: 13, color: "var(--text-primary)" }}>{rt.agentRuntimeName || rt.name || rt.agentRuntimeId}</span>
                    <span style={{
                      fontSize: 11, padding: "2px 8px", borderRadius: 4,
                      background: rt.status === "ACTIVE" ? "var(--active-status-bg)" : "var(--bg-surface-alt)",
                      color: rt.status === "ACTIVE" ? "var(--active-status-text)" : "var(--text-secondary)",
                    }}>
                      {rt.status || "UNKNOWN"}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: "auto" }}>
                      <i className="bi bi-x-circle" style={{ marginRight: 4 }} />No OTEL traces
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {otelEnabled && (
        <>
          <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
            <input placeholder="Agent ID" value={agentId} onChange={(e) => setAgentId(e.target.value)}
              style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-input)", color: "var(--text-primary)", flex: 1 }} />
            <input placeholder="Session ID" value={sessionId} onChange={(e) => setSessionId(e.target.value)}
              style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-input)", color: "var(--text-primary)", flex: 1 }} />
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-secondary)", cursor: "pointer" }}>
              <input type="checkbox" checked={errorOnly} onChange={(e) => setErrorOnly(e.target.checked)} /> Errors only
            </label>
          </div>

          <div style={{ display: "flex", gap: 20 }}>
            <div style={{ width: 400, flexShrink: 0 }}>
              <Card title="Traces">
                {loading && <Loading />}
                {error && <ErrorMsg msg={error} />}
                {traces.map((t, i) => (
                  <div
                    key={i}
                    onClick={() => setSelectedTrace(t.traceId || null)}
                    style={{
                      padding: "10px 12px", cursor: "pointer", borderRadius: 6, marginBottom: 4,
                      background: selectedTrace === t.traceId ? "var(--bg-hover)" : "transparent",
                      borderLeft: selectedTrace === t.traceId ? "3px solid var(--accent-text)" : "3px solid transparent",
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{t.operation || t.traceId?.slice(0, 16)}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", gap: 12 }}>
                      <span>{t.latency_ms ? `${t.latency_ms}ms` : "—"}</span>
                      <span>{t["@timestamp"] ? new Date(t["@timestamp"]).toLocaleTimeString() : ""}</span>
                      {t.error_type && <span style={{ color: "#ef4444" }}><i className="bi bi-exclamation-triangle" /> {t.error_type}</span>}
                    </div>
                  </div>
                ))}
                {traces.length === 0 && !loading && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No traces found</div>}
              </Card>
            </div>

            <div style={{ flex: 1 }}>
              <Card title={selectedTrace ? `Trace: ${selectedTrace.slice(0, 20)}…` : "Waterfall"}>
                {!selectedTrace && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Select a trace to view spans</div>}
                {traceDetail?.spans.map((s, i) => (
                  <WaterfallSpan key={i} span={s} maxDuration={maxDuration} />
                ))}
              </Card>

              {traceDetail && selectedTrace && (
                <Card title="Span Details" style={{ marginTop: 16 }}>
                  <pre style={{ fontSize: 12, color: "var(--pre-text)", overflow: "auto", maxHeight: 300 }}>
                    {JSON.stringify(traceDetail.spans, null, 2)}
                  </pre>
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
