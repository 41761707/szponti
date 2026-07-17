import type { StageName, WorkflowProfile } from "@/types";

const ALL_STAGES: StageName[] = [
  "tech-project",
  "develop",
  "cr",
  "scenariusze-testowe",
  "db-context",
  "git-push",
];

type Preset = "full" | "develop_cr" | "cr_only" | "techproject_only";

interface StageSelectorProps {
  profile: WorkflowProfile;
  onChange: (profile: WorkflowProfile) => void;
}

function applyPreset(preset: Preset, current: WorkflowProfile): WorkflowProfile {
  if (preset === "full") {
    return {
      ...current,
      enabled_stages: [...ALL_STAGES.filter((stage) => stage !== "git-push")],
    };
  }
  if (preset === "develop_cr") {
    return {
      ...current,
      enabled_stages: ["develop", "cr", "db-context"],
    };
  }
  if (preset === "cr_only") {
    return {
      ...current,
      enabled_stages: ["cr", "db-context"],
    };
  }
  return {
    ...current,
    enabled_stages: ["tech-project", "db-context"],
  };
}

export function StageSelector({ profile, onChange }: StageSelectorProps) {
  const toggleStage = (stage: StageName) => {
    const enabled = profile.enabled_stages.includes(stage)
      ? profile.enabled_stages.filter((item) => item !== stage)
      : [...profile.enabled_stages, stage];
    onChange({ ...profile, enabled_stages: enabled });
  };

  const needsTechInput =
    profile.enabled_stages.includes("develop") &&
    !profile.enabled_stages.includes("tech-project");
  const needsDevelopInput =
    profile.enabled_stages.includes("cr") &&
    !profile.enabled_stages.includes("develop");
  const dbContextEnabled = profile.enabled_stages.includes("db-context");

  return (
    <section className="panel stage-selector">
      <h2>Profil etapów</h2>
      <div className="preset-row">
        {(
          ["full", "develop_cr", "cr_only", "techproject_only"] as Preset[]
        ).map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => onChange(applyPreset(preset, profile))}
          >
            {preset}
          </button>
        ))}
      </div>
      <div className="checkbox-grid">
        {ALL_STAGES.map((stage) => (
          <label key={stage} className="stage-check">
            <input
              type="checkbox"
              checked={profile.enabled_stages.includes(stage)}
              onChange={() => toggleStage(stage)}
            />
            <span>{stage}</span>
          </label>
        ))}
      </div>
      <p className="muted">
        Gdy db-context wyłączony, odczyt bazy przez MCP nie będzie
        uruchamiany mimo DB_STATUS: POTRZEBNE_DANE.
      </p>
      {needsTechInput ? (
        <label>
          stage_inputs[tech-project]
          <textarea
            rows={4}
            value={profile.stage_inputs["tech-project"] ?? ""}
            onChange={(event) =>
              onChange({
                ...profile,
                stage_inputs: {
                  ...profile.stage_inputs,
                  "tech-project": event.target.value,
                },
              })
            }
          />
        </label>
      ) : null}
      {needsDevelopInput ? (
        <label>
          stage_inputs[develop]
          <textarea
            rows={4}
            value={profile.stage_inputs.develop ?? ""}
            onChange={(event) =>
              onChange({
                ...profile,
                stage_inputs: {
                  ...profile.stage_inputs,
                  develop: event.target.value,
                },
              })
            }
          />
        </label>
      ) : null}
      {profile.enabled_stages.includes("git-push") ? (
        <label className="authorize-label">
          <input
            type="checkbox"
            checked={profile.authorize_push}
            onChange={(event) =>
              onChange({ ...profile, authorize_push: event.target.checked })
            }
          />
          authorize_push
        </label>
      ) : null}
      <div className="field-grid">
        <label>
          cr_max_iterations
          <input
            type="number"
            min={1}
            value={profile.cr_max_iterations}
            onChange={(event) =>
              onChange({
                ...profile,
                cr_max_iterations: Number(event.target.value) || 1,
              })
            }
          />
        </label>
        {dbContextEnabled ? (
          <label>
            db_context_max_iterations
            <input
              type="number"
              min={1}
              value={profile.db_context_max_iterations}
              onChange={(event) =>
                onChange({
                  ...profile,
                  db_context_max_iterations: Number(event.target.value) || 1,
                })
              }
            />
          </label>
        ) : null}
      </div>
    </section>
  );
}
