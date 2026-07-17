import type { StageRun } from "@/types";

interface StageCardProps {
  stage: StageRun;
  onRetry?: (stageName: string) => void;
  canRetry?: boolean;
}

export function StageCard({ stage, onRetry, canRetry }: StageCardProps) {
  const copyOutput = async () => {
    if (!stage.output) {
      return;
    }
    await navigator.clipboard.writeText(stage.output);
  };

  return (
    <article className={`stage-card status-${stage.status}`}>
      <header>
        <h3>{stage.name}</h3>
        <span>{stage.status}</span>
      </header>
      <p className="muted">
        {stage.worker_name ?? "—"}
        {stage.attempt != null ? ` · attempt ${stage.attempt}` : ""}
        {stage.run_id ? ` · run ${stage.run_id}` : ""}
      </p>
      {stage.error_message ? (
        <p className="error-text">{stage.error_message}</p>
      ) : null}
      <pre className="stage-output">{stage.output || "—"}</pre>
      <div className="inline-actions">
        <button type="button" onClick={() => void copyOutput()}>
          Copy
        </button>
        {canRetry && onRetry ? (
          <button type="button" onClick={() => onRetry(stage.name)}>
            Retry stage
          </button>
        ) : null}
      </div>
    </article>
  );
}
