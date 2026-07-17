import { useEffect, useRef } from "react";

import type { WorkflowEvent } from "@/types";

interface RunLogProps {
  events: WorkflowEvent[];
  stageFilter: string;
  onFilterChange: (value: string) => void;
}

type LogEntry =
  | {
      kind: "status";
      id: string;
      createdAt: string;
      type: string;
      stageName: string;
      body: string;
      isError: boolean;
    }
  | {
      kind: "stream";
      id: string;
      createdAt: string;
      stageName: string;
      text: string;
    };

function statusBody(event: WorkflowEvent): string {
  const parts: string[] = [];
  if (event.message?.trim()) {
    parts.push(event.message);
  }
  const errorType = event.payload?.error_type;
  if (typeof errorType === "string" && errorType.trim()) {
    parts.push(`[${errorType}]`);
  }
  if (parts.length === 0 && event.type.includes("failed")) {
    return "(brak treści błędu — sprawdź terminal backendu)";
  }
  return parts.join(" ");
}

function chunkText(event: WorkflowEvent): string {
  const fromPayload = event.payload?.chunk;
  if (typeof fromPayload === "string") {
    return fromPayload;
  }
  return event.message ?? "";
}

/** Merge consecutive output_chunk events into continuous chat streams. */
export function buildLogEntries(events: WorkflowEvent[]): LogEntry[] {
  const entries: LogEntry[] = [];
  for (const event of events) {
    if (event.type === "output_chunk") {
      const stageName = event.stage_name ?? "—";
      const text = chunkText(event);
      const last = entries[entries.length - 1];
      if (
        last?.kind === "stream" &&
        last.stageName === stageName
      ) {
        last.text += text;
        continue;
      }
      entries.push({
        kind: "stream",
        id: event.id,
        createdAt: event.created_at,
        stageName,
        text,
      });
      continue;
    }
    entries.push({
      kind: "status",
      id: event.id,
      createdAt: event.created_at,
      type: event.type,
      stageName: event.stage_name ?? "—",
      body: statusBody(event),
      isError: event.type.includes("failed"),
    });
  }
  return entries;
}

export function RunLog({ events, stageFilter, onFilterChange }: RunLogProps) {
  const filtered = stageFilter
    ? events.filter((event) => (event.stage_name ?? "").includes(stageFilter))
    : events;
  const entries = buildLogEntries(filtered);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const streamLen =
    entries.length > 0 && entries[entries.length - 1]?.kind === "stream"
      ? (entries[entries.length - 1] as Extract<LogEntry, { kind: "stream" }>)
          .text.length
      : 0;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries.length, streamLen]);

  return (
    <section className="panel run-log">
      <div className="timeline-header">
        <h2>Logi</h2>
        <input
          placeholder="Filtr etapu"
          value={stageFilter}
          onChange={(event) => onFilterChange(event.target.value)}
        />
      </div>
      <div className="log-stream chat-stream">
        {entries.map((entry) =>
          entry.kind === "stream" ? (
            <article key={entry.id} className="chat-bubble">
              <header className="chat-bubble-meta">
                <time>{new Date(entry.createdAt).toLocaleTimeString()}</time>
                <span className="chat-stage">{entry.stageName}</span>
              </header>
              <pre className="chat-bubble-text">{entry.text || "…"}</pre>
            </article>
          ) : (
            <div
              key={entry.id}
              className={
                entry.isError
                  ? "log-status log-status-error"
                  : "log-status"
              }
            >
              <time>{new Date(entry.createdAt).toLocaleTimeString()}</time>
              <span className="log-type">{entry.type}</span>
              <span>{entry.stageName}</span>
              <span className="log-status-body">{entry.body}</span>
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>
    </section>
  );
}
