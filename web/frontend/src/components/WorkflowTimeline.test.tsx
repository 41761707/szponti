import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkflowTimeline } from "@/components/WorkflowTimeline";
import type { StageRun, WorkflowProfile } from "@/types";

const baseProfile: WorkflowProfile = {
  enabled_stages: [
    "tech-project",
    "develop",
    "cr",
    "scenariusze-testowe",
    "db-context",
  ],
  stage_inputs: {},
  authorize_push: false,
  cr_max_iterations: 5,
  db_context_max_iterations: 3,
};

function stage(name: string, worker: string, status: string): StageRun {
  return {
    name,
    status,
    output: "",
    worker_name: worker,
  };
}

describe("WorkflowTimeline", () => {
  it("shows db-context as skipped when disabled in profile", () => {
    const profile: WorkflowProfile = {
      ...baseProfile,
      enabled_stages: baseProfile.enabled_stages.filter(
        (item) => item !== "db-context",
      ),
    };
    render(
      <WorkflowTimeline profile={profile} stages={[]} status="running" />,
    );
    const item = screen.getByText("db-context").closest("li");
    expect(item?.textContent).toContain("skipped");
    expect(item?.textContent).not.toContain("auto");
  });

  it("shows db-context as pending when enabled and no runs exist", () => {
    render(
      <WorkflowTimeline profile={baseProfile} stages={[]} status="running" />,
    );
    const item = screen.getByText("db-context").closest("li");
    expect(item?.textContent).toContain("pending");
    expect(item?.textContent).not.toContain("auto");
  });

  it("shows db-context status from latest stage run", () => {
    render(
      <WorkflowTimeline
        profile={baseProfile}
        stages={[stage("run_db_context#1", "db-context", "completed")]}
        status="running"
      />,
    );
    const item = screen.getByText("db-context").closest("li");
    expect(item?.textContent).toContain("completed");
  });

  it("shows not_requested when workflow finished without db-context runs", () => {
    render(
      <WorkflowTimeline profile={baseProfile} stages={[]} status="completed" />,
    );
    const item = screen.getByText("db-context").closest("li");
    expect(item?.textContent).toContain("not_requested");
  });
});
