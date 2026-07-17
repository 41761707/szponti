import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StageSelector } from "@/components/StageSelector";
import type { WorkflowProfile } from "@/types";

const baseProfile: WorkflowProfile = {
  enabled_stages: ["tech-project"],
  stage_inputs: {},
  authorize_push: false,
  cr_max_iterations: 5,
  db_context_max_iterations: 3,
};

describe("StageSelector", () => {
  it("renders stage checkboxes and presets", () => {
    render(<StageSelector profile={baseProfile} onChange={() => undefined} />);
    expect(screen.getByText("tech-project")).toBeTruthy();
    expect(screen.getByText("db-context")).toBeTruthy();
    expect(screen.getByText("develop_cr")).toBeTruthy();
    expect(screen.getByText("cr_only")).toBeTruthy();
  });

  it("does not show auto-run message for db-context", () => {
    render(<StageSelector profile={baseProfile} onChange={() => undefined} />);
    expect(
      screen.queryByText(/uruchamia się automatycznie/i),
    ).toBeNull();
  });

  it("full preset includes db-context", () => {
    const onChange = vi.fn();
    render(<StageSelector profile={baseProfile} onChange={onChange} />);
    fireEvent.click(screen.getByText("full"));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled_stages: expect.arrayContaining(["db-context"]),
      }),
    );
  });

  it("unchecking db-context removes it from enabled_stages", () => {
    const profile: WorkflowProfile = {
      ...baseProfile,
      enabled_stages: ["tech-project", "db-context"],
    };
    const onChange = vi.fn();
    render(<StageSelector profile={profile} onChange={onChange} />);
    const checkbox = screen.getByRole("checkbox", { name: "db-context" });
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith({
      ...profile,
      enabled_stages: ["tech-project"],
    });
  });

  it("checking db-context adds it to enabled_stages", () => {
    const onChange = vi.fn();
    render(<StageSelector profile={baseProfile} onChange={onChange} />);
    const checkbox = screen.getByRole("checkbox", { name: "db-context" });
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith({
      ...baseProfile,
      enabled_stages: ["tech-project", "db-context"],
    });
  });

  it("hides db_context_max_iterations when db-context disabled", () => {
    render(<StageSelector profile={baseProfile} onChange={() => undefined} />);
    expect(screen.queryByText("db_context_max_iterations")).toBeNull();
  });

  it("shows db_context_max_iterations when db-context enabled", () => {
    const profile: WorkflowProfile = {
      ...baseProfile,
      enabled_stages: ["tech-project", "db-context"],
    };
    render(<StageSelector profile={profile} onChange={() => undefined} />);
    expect(screen.getByText("db_context_max_iterations")).toBeTruthy();
  });
});
