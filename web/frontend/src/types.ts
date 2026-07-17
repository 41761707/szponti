export type StageName =
  | "tech-project"
  | "develop"
  | "cr"
  | "scenariusze-testowe"
  | "db-context"
  | "git-push";

export interface ConfigOverrides {
  workspace?: string | null;
  env_file?: string | null;
  skills_dir?: string | null;
  mcp_config_file?: string | null;
  model?: string | null;
  api_key?: string | null;
}

export interface WorkflowProfile {
  enabled_stages: StageName[];
  stage_inputs: Record<string, string>;
  authorize_push: boolean;
  cr_max_iterations: number;
  db_context_max_iterations: number;
  techproject_feedback?: string | null;
}

export interface TaskConfig {
  signature: string;
  task_description: string;
}

export interface StageRun {
  name: string;
  status: string;
  output: string;
  worker_name?: string | null;
  agent_id?: string | null;
  run_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  attempt?: number | null;
  error_message?: string | null;
}

export interface WorkflowRun {
  id: string;
  task: TaskConfig;
  profile: WorkflowProfile;
  status: string;
  stages: StageRun[];
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
}

export interface WorkflowEvent {
  id: string;
  workflow_id: string;
  type: string;
  stage_name?: string | null;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ConfigDefaults {
  workspace: string;
  skills_dir: string;
  mcp_config_file: string;
  model: string;
  env_files: string[];
  api_key: string;
}

export interface ValidateResponse {
  ok: boolean;
  errors: string[];
  warnings: string[];
  task_preview?: TaskConfig | null;
}
