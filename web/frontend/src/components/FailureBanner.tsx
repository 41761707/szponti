import type { StageRun, WorkflowEvent } from "@/types";

interface FailureBannerProps {
  status: string;
  events: WorkflowEvent[];
  stages: StageRun[];
}

export function FailureBanner({ status, events, stages }: FailureBannerProps) {
  if (status !== "failed") {
    return null;
  }
  const failedEvent = [...events]
    .reverse()
    .find((event) => event.type === "workflow_failed");
  const failedStage = [...stages]
    .reverse()
    .find(
      (stage) =>
        stage.status === "failed" || Boolean(stage.error_message?.trim()),
    );
  const message =
    failedEvent?.message?.trim() ||
    failedStage?.error_message?.trim() ||
    failedStage?.output?.trim()?.slice(0, 500) ||
    "Workflow failed — szczegóły powinny być w Logach albo w terminalu backendu (uvicorn).";

  return (
    <div className="banner error">
      <div>
        <strong>Workflow failed</strong>
        <pre className="failure-detail">{message}</pre>
        <p className="muted">
          Szukaj też: terminal z uvicorn, karta etapu ze statusem failed, event
          workflow_failed w Logach.
        </p>
      </div>
    </div>
  );
}
