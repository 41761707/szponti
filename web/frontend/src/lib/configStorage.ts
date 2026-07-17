/** Persist dashboard config in the browser (not secrets to disk beyond localStorage). */

import type { ConfigOverrides, WorkflowProfile } from "@/types";

const STORAGE_KEY = "szponti.dashboard.config.v1";

/** v2: db-context toggle — explicit disable must persist across reloads. */
export const PERSISTED_CONFIG_SCHEMA_VERSION = 2;

export interface PersistedDashboardConfig {
  config: ConfigOverrides;
  taskPath: string;
  signature: string;
  taskDescription: string;
  usePath: boolean;
  profile?: WorkflowProfile;
  validated?: boolean;
  schemaVersion?: number;
}

/** One-time migration for profiles saved before db-context toggle (schema v1). */
export function migrateLegacyProfile(
  profile: WorkflowProfile,
  schemaVersion: number | undefined,
): WorkflowProfile {
  if (
    schemaVersion !== undefined &&
    schemaVersion >= PERSISTED_CONFIG_SCHEMA_VERSION
  ) {
    return profile;
  }
  if (profile.enabled_stages.includes("db-context")) {
    return profile;
  }
  return {
    ...profile,
    enabled_stages: [...profile.enabled_stages, "db-context"],
  };
}

export function migratePersistedConfig(
  config: PersistedDashboardConfig,
): PersistedDashboardConfig {
  if (!config.profile) {
    return config;
  }
  return {
    ...config,
    profile: migrateLegacyProfile(config.profile, config.schemaVersion),
  };
}

export function loadPersistedConfig(): PersistedDashboardConfig | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as PersistedDashboardConfig;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    return migratePersistedConfig(parsed);
  } catch {
    return null;
  }
}

export function savePersistedConfig(data: PersistedDashboardConfig): void {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      ...data,
      schemaVersion: PERSISTED_CONFIG_SCHEMA_VERSION,
    }),
  );
}

export function summarizeConfig(data: {
  config: ConfigOverrides;
  taskPath: string;
  signature: string;
  usePath: boolean;
}): string[] {
  const lines: string[] = [];
  if (data.usePath && data.taskPath.trim()) {
    lines.push(`Plik zadania: ${data.taskPath}`);
  } else if (!data.usePath && data.signature.trim()) {
    lines.push(`Sygnatura: ${data.signature}`);
  }
  const { config } = data;
  if (config.model) {
    lines.push(`Model: ${config.model}`);
  }
  if (config.workspace) {
    lines.push(`Workspace: ${config.workspace}`);
  }
  if (config.env_file) {
    lines.push(`Env file: ${config.env_file}`);
  }
  if (config.skills_dir) {
    lines.push(`Skills dir: ${config.skills_dir}`);
  }
  if (config.mcp_config_file) {
    lines.push(`MCP config: ${config.mcp_config_file}`);
  }
  if (config.api_key) {
    lines.push("API key: ustawiony (ukryty)");
  }
  if (lines.length === 0) {
    lines.push("Zapisano puste nadpisania — użyte będą domyślne wartości środowiska.");
  }
  return lines;
}
