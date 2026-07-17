import type { StageName, StageRun, WorkflowProfile } from "@/types";

const PIPELINE: StageName[] = [
  "tech-project",
  "develop",
  "cr",
  "scenariusze-testowe",
  "db-context",
  "git-push",
];

const TERMINAL_WORKFLOW_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
]);

interface WorkflowTimelineProps {
  profile: WorkflowProfile;
  stages: StageRun[];
  status: string;
}

function matchesStage(stage: StageRun, stageName: string): boolean {
  const worker = (stage.worker_name ?? "").toLowerCase();
  const name = stage.name.toLowerCase();
  if (stageName === "db-context") {
    return (
      worker === "db-context" ||
      name.includes("db-context") ||
      name.includes("run_db_context")
    );
  }
  if (stageName === "tech-project") {
    return (
      worker === "techproject" ||
      worker === "tech-project" ||
      name.includes("techproject") ||
      name.includes("tech-project")
    );
  }
  return (
    worker === stageName ||
    name === stageName ||
    name.startsWith(`${stageName}#`) ||
    name.includes(stageName)
  );
}

function resolveStatus(
  stageName: StageName,
  profile: WorkflowProfile,
  stages: StageRun[],
  workflowStatus: string,
): string {
  if (!profile.enabled_stages.includes(stageName)) {
    return "skipped";
  }
  const matches = stages.filter((stage) => matchesStage(stage, stageName));
  if (matches.length === 0) {
    if (
      stageName === "db-context" &&
      TERMINAL_WORKFLOW_STATUSES.has(workflowStatus)
    ) {
      return "not_requested";
    }
    return "pending";
  }
  return matches[matches.length - 1]?.status ?? "pending";
}

function countAttempts(stages: StageRun[], stageName: string): number {
  return stages.filter((stage) => matchesStage(stage, stageName)).length;
}

export function WorkflowTimeline({
  profile,
  stages,
  status,
}: WorkflowTimelineProps) {
  const crLoop = Math.max(
    countAttempts(stages, "develop"),
    countAttempts(stages, "cr"),
  );
  const dbLoop = countAttempts(stages, "db-context");

  return (
    <section className="panel timeline">
      <div className="timeline-header">
        <h2>Pipeline</h2>
        <span className={`status-pill status-${status}`}>{status}</span>
      </div>
      <div className="loop-counters">
        <span>CR↔develop: {crLoop}</span>
        <span>db-context: {dbLoop}</span>
      </div>
      <ol className="timeline-track">
        {PIPELINE.map((stageName) => {
          const stageStatus = resolveStatus(
            stageName,
            profile,
            stages,
            status,
          );
          return (
            <li key={stageName} className={`timeline-item status-${stageStatus}`}>
              <span className="dot" />
              <strong>{stageName}</strong>
              <span>{stageStatus}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
