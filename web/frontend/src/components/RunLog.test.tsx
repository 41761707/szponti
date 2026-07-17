import { describe, expect, it } from "vitest";

import { buildLogEntries } from "@/components/RunLog";
import type { WorkflowEvent } from "@/types";

function chunk(
  id: string,
  stage: string,
  text: string,
): WorkflowEvent {
  return {
    id,
    workflow_id: "wf",
    type: "output_chunk",
    stage_name: stage,
    message: text,
    payload: { chunk: text },
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("buildLogEntries", () => {
  it("merges consecutive output chunks into one stream", () => {
    const entries = buildLogEntries([
      chunk("1", "prepare_techproject#1", "Prz"),
      chunk("2", "prepare_techproject#1", "eglądam"),
      chunk("3", "prepare_techproject#1", " repo"),
    ]);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      kind: "stream",
      text: "Przeglądam repo",
    });
  });

  it("splits streams when stage changes", () => {
    const entries = buildLogEntries([
      chunk("1", "develop#1", "A"),
      chunk("2", "cr#1", "B"),
    ]);
    expect(entries).toHaveLength(2);
  });
});
