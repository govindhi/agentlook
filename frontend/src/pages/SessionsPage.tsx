import { useState } from "react";
import { useFetch } from "../hooks/useFetch";
import { Card } from "../components/Card";
import { Loading, ErrorMsg } from "../components/Feedback";

interface SessionSummary { sessionId: string; actorId: string; createdAt: string }
interface Event {
  eventId: string;
  eventTimestamp: string;
  payload?: { conversational?: { content?: { text?: string }; role?: string } }[];
  metadata?: Record<string, { stringValue?: string }>;
}

export default function SessionsPage() {
  const [memoryId, setMemoryId] = useState("");
  const [actorId, setActorId] = useState("");
  const [selectedSession, setSelectedSession] = useState<string | null>(null);

  const sessionsPath = memoryId && actorId ? `/api/sessions/${memoryId}/list?actor_id=${actorId}` : null;
  const eventsPath = memoryId && selectedSession && actorId
    ? `/api/sessions/${memoryId}/${selectedSession}/events?actor_id=${actorId}`
    : null;

  const { data: sessions, loading: sLoad, error: sErr } = useFetch<SessionSummary[]>(sessionsPath);
  const { data: events, loading: eLoad, error: eErr } = useFetch<Event[]>(eventsPath);

  const roleColors: Record<string, string> = { USER: "#3b82f6", ASSISTANT: "#10b981", TOOL: "#f59e0b", OTHER: "#6b7280" };

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: 20 }}>Session Explorer</h1>

      <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
        <input placeholder="Memory ID" value={memoryId} onChange={(e) => setMemoryId(e.target.value)}
          style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-input)", color: "var(--text-primary)", flex: 1 }} />
        <input placeholder="Actor ID" value={actorId} onChange={(e) => setActorId(e.target.value)}
          style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-input)", color: "var(--text-primary)", flex: 1 }} />
      </div>

      <div style={{ display: "flex", gap: 20 }}>
        <div style={{ width: 320, flexShrink: 0 }}>
          <Card title="Sessions">
            {sLoad && <Loading />}
            {sErr && <ErrorMsg msg={sErr} />}
            {sessions?.map((s) => (
              <div
                key={s.sessionId}
                onClick={() => setSelectedSession(s.sessionId)}
                style={{
                  padding: "10px 12px", cursor: "pointer", borderRadius: 6, marginBottom: 4,
                  background: selectedSession === s.sessionId ? "var(--bg-hover)" : "transparent",
                  borderLeft: selectedSession === s.sessionId ? "3px solid var(--accent-text)" : "3px solid transparent",
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600 }}>{s.sessionId.slice(0, 16)}…</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{new Date(s.createdAt).toLocaleString()}</div>
              </div>
            ))}
            {sessions?.length === 0 && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No sessions found</div>}
          </Card>
        </div>

        <div style={{ flex: 1 }}>
          <Card title="Conversation">
            {eLoad && <Loading />}
            {eErr && <ErrorMsg msg={eErr} />}
            {!selectedSession && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Select a session to view events</div>}
            {events?.map((ev) => {
              const msgs = ev.payload || [];
              return msgs.map((p, pi) => {
                const role = p.conversational?.role || "OTHER";
                const text = p.conversational?.content?.text || "(binary payload)";
                return (
                  <div key={`${ev.eventId}-${pi}`} style={{ marginBottom: 12, display: "flex", flexDirection: role === "USER" ? "row-reverse" : "row" }}>
                    <div
                      style={{
                        maxWidth: "75%", padding: "10px 14px", borderRadius: 12,
                        background: roleColors[role] || "var(--btn-bg)", color: "#fff", fontSize: 14,
                      }}
                    >
                      <div style={{ fontSize: 10, opacity: 0.7, marginBottom: 4 }}>{role} · {new Date(ev.eventTimestamp).toLocaleTimeString()}</div>
                      <div style={{ whiteSpace: "pre-wrap" }}>{text}</div>
                    </div>
                  </div>
                );
              });
            })}
          </Card>
        </div>
      </div>
    </div>
  );
}
