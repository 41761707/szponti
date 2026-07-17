import type {
  ConfigDefaults,
  ConfigOverrides,
  TaskConfig,
  ValidateResponse,
  WorkflowEvent,
  WorkflowProfile,
  WorkflowRun,
} from "@/types";

const API_BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getDefaults(): Promise<ConfigDefaults> {
  return request<ConfigDefaults>("/api/config/defaults");
}

export async function validateConfig(body: {
  config?: ConfigOverrides | null;
  profile?: WorkflowProfile | null;
  task_config_path?: string | null;
}): Promise<ValidateResponse> {
  const response = await fetch(`${API_BASE}/api/config/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await response.json()) as ValidateResponse;
  // 400 z listą błędów to normalny wynik walidacji (§6.6)
  if (response.status === 400 && Array.isArray(data.errors)) {
    return data;
  }
  if (!response.ok) {
    throw new Error(JSON.stringify(data) || `HTTP ${response.status}`);
  }
  return data;
}

export async function listSkills(skillsDir?: string): Promise<string[]> {
  const params = new URLSearchParams();
  if (skillsDir) {
    params.set("skills_dir", skillsDir);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const data = await request<{ skills: string[] }>(
    `/api/config/skills${suffix}`,
  );
  return data.skills;
}

export async function browseTasks(
  root?: string,
  q?: string,
): Promise<string[]> {
  const params = new URLSearchParams();
  if (root) {
    params.set("root", root);
  }
  if (q) {
    params.set("q", q);
  }
  const suffix = params.toString() ? `?${params}` : "";
  const data = await request<{ files: string[] }>(`/api/tasks/browse${suffix}`);
  return data.files;
}

export async function previewTask(taskConfigPath: string): Promise<TaskConfig> {
  return request<TaskConfig>("/api/tasks/preview", {
    method: "POST",
    body: JSON.stringify({ task_config_path: taskConfigPath }),
  });
}

export async function startWorkflow(body: {
  task:
    | { task_config_path: string }
    | { task_description: string; signature: string };
  profile: WorkflowProfile;
  config?: ConfigOverrides | null;
}): Promise<WorkflowRun> {
  return request<WorkflowRun>("/api/workflows", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listWorkflows(): Promise<WorkflowRun[]> {
  return request<WorkflowRun[]>("/api/workflows");
}

export async function getWorkflow(id: string): Promise<WorkflowRun> {
  return request<WorkflowRun>(`/api/workflows/${id}`);
}

export async function deleteWorkflow(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/workflows/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
}

export async function sendCommand(
  id: string,
  body: {
    type: "stop" | "retry_stage";
    stage_name?: string;
    payload?: Record<string, string>;
  },
): Promise<WorkflowRun> {
  return request<WorkflowRun>(`/api/workflows/${id}/commands`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function subscribeEvents(
  workflowId: string,
  onEvent: (event: WorkflowEvent) => void,
): () => void {
  const source = new EventSource(`/api/workflows/${workflowId}/events`);
  let closed = false;

  const close = () => {
    if (closed) {
      return;
    }
    closed = true;
    source.close();
  };

  const handler = (message: MessageEvent<string>) => {
    try {
      const parsed = JSON.parse(message.data) as WorkflowEvent;
      onEvent(parsed);
      // po terminalu zamykamy SSE — inaczej EventSource reconnect spamuje logi
      if (
        parsed.type === "workflow_completed" ||
        parsed.type === "workflow_failed" ||
        parsed.type === "workflow_cancelled"
      ) {
        close();
      }
    } catch {
      // ignorujemy nieparsowalne chunki SSE
    }
  };
  source.onmessage = handler;
  source.addEventListener("output_chunk", handler);
  source.addEventListener("stage_started", handler);
  source.addEventListener("stage_completed", handler);
  source.addEventListener("stage_failed", handler);
  source.addEventListener("stage_skipped", handler);
  source.addEventListener("workflow_started", handler);
  source.addEventListener("workflow_completed", handler);
  source.addEventListener("workflow_failed", handler);
  source.addEventListener("workflow_cancelled", handler);
  source.onerror = () => {
    // zakończony stream / reconnect — nie zapętlamy przy closed
    if (source.readyState === EventSource.CLOSED) {
      close();
    }
  };
  return close;
}
