import type { WorkflowRun } from "@/types";

interface RunSidebarProps {
  runs: WorkflowRun[];
  activeRunId: string | null;
  view: "workflow" | "config";
  onViewChange: (view: "workflow" | "config") => void;
  onSelectRun: (run: WorkflowRun) => void;
  onDeleteRun: (runId: string) => void;
}

export function RunSidebar({
  runs,
  activeRunId,
  view,
  onViewChange,
  onSelectRun,
  onDeleteRun,
}: RunSidebarProps) {
  return (
    <aside className="sidebar">
      <h1>Szponti</h1>
      <p className="muted">Orchestrator dashboard</p>
      <nav className="side-nav">
        <button
          type="button"
          className={view === "workflow" ? "nav-item active" : "nav-item"}
          onClick={() => onViewChange("workflow")}
        >
          Workflow
        </button>
        <button
          type="button"
          className={view === "config" ? "nav-item active" : "nav-item"}
          onClick={() => onViewChange("config")}
        >
          Konfiguracja
        </button>
      </nav>
      <h2>Ostatnie runy</h2>
      <ul className="run-list">
        {runs.map((run) => (
          <li key={run.id} className="run-list-item">
            <button
              type="button"
              className={
                activeRunId === run.id ? "run-select active" : "run-select"
              }
              onClick={() => onSelectRun(run)}
            >
              <strong>{run.task.signature || run.id.slice(0, 8)}</strong>
              <span>{run.status}</span>
            </button>
            <button
              type="button"
              className="run-delete"
              title="Usuń z historii"
              aria-label={`Usuń run ${run.task.signature || run.id.slice(0, 8)}`}
              onClick={(event) => {
                event.stopPropagation();
                onDeleteRun(run.id);
              }}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}

interface WorkflowActionsProps {
  canStart: boolean;
  canStop: boolean;
  retryFeedback: string;
  onStart: () => void;
  onStop: () => void;
  onRetryFeedbackChange: (value: string) => void;
}

export function WorkflowActions({
  canStart,
  canStop,
  retryFeedback,
  onStart,
  onStop,
  onRetryFeedbackChange,
}: WorkflowActionsProps) {
  return (
    <div className="actions-bar-block">
      <div className="actions-bar">
        <button type="button" className="primary" onClick={onStart}>
          Start workflow
        </button>
        <button type="button" onClick={onStop}>
          Stop
        </button>
        <label>
          Retry feedback (tech-project)
          <input
            value={retryFeedback}
            onChange={(event) => onRetryFeedbackChange(event.target.value)}
          />
        </label>
      </div>
      {!canStart ? (
        <p className="action-hint">
          Start wymaga zweryfikowanej konfiguracji: Konfiguracja → Zapisz i
          zweryfikuj (albo nie zmieniaj pól po zapisie).
        </p>
      ) : null}
      {!canStop ? (
        <p className="action-hint muted">
          Stop jest dostępny, gdy run ma status running lub queued.
        </p>
      ) : null}
    </div>
  );
}
