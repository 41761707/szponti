import { beforeEach, describe, expect, it } from "vitest";

import {
  PERSISTED_CONFIG_SCHEMA_VERSION,
  loadPersistedConfig,
  migrateLegacyProfile,
  savePersistedConfig,
  type PersistedDashboardConfig,
} from "@/lib/configStorage";
import type { WorkflowProfile } from "@/types";

const STORAGE_KEY = "szponti.dashboard.config.v1";

const baseProfile: WorkflowProfile = {
  enabled_stages: ["tech-project", "develop", "cr"],
  stage_inputs: {},
  authorize_push: false,
  cr_max_iterations: 5,
  db_context_max_iterations: 3,
};

const baseConfig: PersistedDashboardConfig = {
  config: {},
  taskPath: "",
  signature: "",
  taskDescription: "",
  usePath: true,
  profile: baseProfile,
  validated: true,
};

class MemoryStorage {
  private store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }

  clear(): void {
    this.store.clear();
  }
}

describe("configStorage profile migration", () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, "localStorage", {
      value: new MemoryStorage(),
      configurable: true,
    });
  });

  it("adds db-context only for legacy schema without explicit version", () => {
    const migrated = migrateLegacyProfile(baseProfile, undefined);
    expect(migrated.enabled_stages).toContain("db-context");
  });

  it("preserves explicit db-context disable for schema v2", () => {
    const disabled: WorkflowProfile = {
      ...baseProfile,
      enabled_stages: ["tech-project", "develop", "cr"],
    };
    const migrated = migrateLegacyProfile(
      disabled,
      PERSISTED_CONFIG_SCHEMA_VERSION,
    );
    expect(migrated.enabled_stages).not.toContain("db-context");
  });

  it("round-trip keeps db-context disabled after reload", () => {
    const disabled: WorkflowProfile = {
      ...baseProfile,
      enabled_stages: ["tech-project", "develop", "cr"],
    };
    savePersistedConfig({ ...baseConfig, profile: disabled });

    const raw = localStorage.getItem(STORAGE_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!) as PersistedDashboardConfig;
    expect(parsed.schemaVersion).toBe(PERSISTED_CONFIG_SCHEMA_VERSION);

    const loaded = loadPersistedConfig();
    expect(loaded?.profile?.enabled_stages).toEqual([
      "tech-project",
      "develop",
      "cr",
    ]);
  });

  it("round-trip keeps db-context enabled when explicitly checked", () => {
    const enabled: WorkflowProfile = {
      ...baseProfile,
      enabled_stages: ["tech-project", "develop", "cr", "db-context"],
    };
    savePersistedConfig({ ...baseConfig, profile: enabled });

    const loaded = loadPersistedConfig();
    expect(loaded?.profile?.enabled_stages).toContain("db-context");
  });
});
