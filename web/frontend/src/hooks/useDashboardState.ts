import { useCallback, useEffect, useState } from "react";

import {
  browseTasks,
  deleteWorkflow,
  getDefaults,
  getWorkflow,
  listSkills,
  listWorkflows,
  previewTask,
  sendCommand,
  startWorkflow,
  subscribeEvents,
  validateConfig,
} from "@/api/client";
import type { ConfigFeedback } from "@/components/ConfigPanel";
import {
  loadPersistedConfig,
  savePersistedConfig,
  summarizeConfig,
} from "@/lib/configStorage";
import type {
  ConfigOverrides,
  TaskConfig,
  WorkflowEvent,
  WorkflowProfile,
  WorkflowRun,
} from "@/types";

type AppView = "workflow" | "config";

const DEFAULT_PROFILE: WorkflowProfile = {
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

export function formatApiError(err: unknown): string | null {
  const raw = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(raw) as {
      detail?: unknown;
      errors?: string[];
    };
    if (Array.isArray(parsed.errors) && parsed.errors.length > 0) {
      return parsed.errors.join("; ");
    }
    if (typeof parsed.detail === "string") {
      if (parsed.detail === "Not Found") {
        return null;
      }
      return parsed.detail;
    }
  } catch {
    // zostaw surowy tekst
  }
  if (raw === "Not Found" || raw.includes('"Not Found"')) {
    return null;
  }
  if (raw.includes("Failed to fetch") || raw.includes("NetworkError")) {
    return (
      "Brak połączenia z API (uruchom backend na :8000 i odśwież stronę)."
    );
  }
  return raw;
}

function collectClientErrors(input: {
  usePath: boolean;
  taskPath: string;
  signature: string;
  taskDescription: string;
}): string[] {
  const errors: string[] = [];
  if (input.usePath) {
    if (!input.taskPath.trim()) {
      errors.push(
        "Podaj ścieżkę do pliku zadania (YAML) albo odznacz " +
          "„Użyj pliku zadania” i wpisz sygnaturę + opis.",
      );
    }
  } else if (!input.signature.trim() || !input.taskDescription.trim()) {
    errors.push("Podaj sygnaturę oraz opis zadania.");
  }
  return errors;
}

/** Keep sidebar order fixed by created_at (newest first). */
function upsertRunByCreatedAt(
  prev: WorkflowRun[],
  fresh: WorkflowRun,
): WorkflowRun[] {
  const others = prev.filter((item) => item.id !== fresh.id);
  return [fresh, ...others].sort(
    (left, right) =>
      Date.parse(right.created_at) - Date.parse(left.created_at),
  );
}

export function useDashboardState() {
  const [view, setView] = useState<AppView>("workflow");
  const [config, setConfig] = useState<ConfigOverrides>({});
  const [profile, setProfile] = useState<WorkflowProfile>(DEFAULT_PROFILE);
  const [usePath, setUsePath] = useState(true);
  const [taskPath, setTaskPath] = useState("");
  const [signature, setSignature] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [skills, setSkills] = useState<string[]>([]);
  const [validationWarnings, setValidationWarnings] = useState<string[]>([]);
  const [validated, setValidated] = useState(false);
  const [taskPreview, setTaskPreview] = useState<TaskConfig | null>(null);
  const [browseFiles, setBrowseFiles] = useState<string[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [activeRun, setActiveRun] = useState<WorkflowRun | null>(null);
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [stageFilter, setStageFilter] = useState("");
  const [retryFeedback, setRetryFeedback] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [configFeedback, setConfigFeedback] = useState<ConfigFeedback>(null);
  const [isSavingConfig, setIsSavingConfig] = useState(false);

  const showError = useCallback((err: unknown) => {
    const message = formatApiError(err);
    if (message) {
      setError(message);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      const saved = loadPersistedConfig();
      let defaultsOk = false;
      try {
        const defaults = await getDefaults();
        defaultsOk = true;
        const fromDefaults: ConfigOverrides = {
          workspace: defaults.workspace,
          skills_dir: defaults.skills_dir,
          mcp_config_file: defaults.mcp_config_file,
          model: defaults.model,
          env_file: defaults.env_files[0] ?? null,
          api_key: "",
        };
        if (saved?.config) {
          setConfig({
            ...fromDefaults,
            ...saved.config,
            api_key: saved.config.api_key || "",
          });
        } else {
          setConfig(fromDefaults);
        }
      } catch {
        if (saved?.config) {
          setConfig(saved.config);
        }
        setConfigFeedback({
          type: "error",
          title: "Nie wczytano domyślnej konfiguracji z API",
          details: [
            "Backend może być wyłączony (oczekiwany :8000).",
            "Możesz wypełnić pola ręcznie i spróbować Zapisz i zweryfikuj.",
          ],
        });
      }
      if (saved) {
        setTaskPath(saved.taskPath ?? "");
        setSignature(saved.signature ?? "");
        setTaskDescription(saved.taskDescription ?? "");
        setUsePath(saved.usePath ?? true);
        if (saved.profile) {
          setProfile(saved.profile);
        }
        // przywróć stan po odświeżeniu — inaczej Start zostaje martwy
        if (saved.validated) {
          setValidated(true);
        }
      }
      try {
        setSkills(await listSkills());
      } catch {
        if (defaultsOk) {
          // skills opcjonalne gdy API działa
        }
      }
      try {
        const history = await listWorkflows();
        setRuns(history);
        if (history[0]) {
          setActiveRun(history[0]);
        }
      } catch {
        // historia opcjonalna
      }
    })();
  }, []);

  useEffect(() => {
    if (!activeRun) {
      return;
    }
    setEvents([]);
    const seen = new Set<string>();
    let refetchTimer: ReturnType<typeof setTimeout> | null = null;
    const scheduleRefresh = () => {
      if (refetchTimer) {
        clearTimeout(refetchTimer);
      }
      refetchTimer = setTimeout(() => {
        void getWorkflow(activeRun.id)
          .then((fresh) => {
            setActiveRun(fresh);
            // aktualizuj w miejscu — bez przenoszenia na górę listy
            setRuns((prev) => upsertRunByCreatedAt(prev, fresh));
          })
          .catch(() => undefined);
      }, 300);
    };

    const unsubscribe = subscribeEvents(activeRun.id, (event) => {
      if (seen.has(event.id)) {
        return;
      }
      seen.add(event.id);
      setEvents((prev) => [...prev, event]);
      // nie odświeżaj stanu przy każdym output_chunk
      if (event.type !== "output_chunk") {
        scheduleRefresh();
      }
    });
    return () => {
      if (refetchTimer) {
        clearTimeout(refetchTimer);
      }
      unsubscribe();
    };
  }, [activeRun?.id]);

  const handleValidate = async () => {
    setError(null);
    setConfigFeedback(null);
    const clientErrors = collectClientErrors({
      usePath,
      taskPath,
      signature,
      taskDescription,
    });
    if (clientErrors.length > 0) {
      setValidated(false);
      setConfigFeedback({
        type: "error",
        title: "Nie zapisano — uzupełnij wymagane pola",
        details: clientErrors,
      });
      return;
    }

    setIsSavingConfig(true);
    try {
      const result = await validateConfig({
        config,
        profile,
        task_config_path: usePath ? taskPath || null : null,
      });
      setValidationWarnings(result.warnings);
      if (result.task_preview) {
        setTaskPreview(result.task_preview);
      }
      if (!result.ok) {
        setValidated(false);
        setConfigFeedback({
          type: "error",
          title: "Walidacja nie powiodła się",
          details:
            result.errors.length > 0
              ? result.errors
              : ["Serwer odrzucił konfigurację bez szczegółów."],
        });
        return;
      }

      savePersistedConfig({
        config,
        taskPath,
        signature,
        taskDescription,
        usePath,
        profile,
        validated: true,
      });
      setValidated(true);
      setConfigFeedback({
        type: "success",
        title: "Zapisano i zweryfikowano konfigurację",
        details: [
          ...summarizeConfig({ config, taskPath, signature, usePath }),
          "Możesz przejść do Workflow i kliknąć Start.",
        ],
      });
      try {
        setSkills(await listSkills(config.skills_dir ?? undefined));
      } catch {
        // lista skilli nie blokuje zapisu
      }
    } catch (err) {
      setValidated(false);
      const message =
        formatApiError(err) || "Nieznany błąd podczas zapisu konfiguracji.";
      setConfigFeedback({
        type: "error",
        title: "Nie udało się zapisać konfiguracji",
        details: [message],
      });
    } finally {
      setIsSavingConfig(false);
    }
  };

  const handleStart = async () => {
    if (!validated) {
      setError(
        "Najpierw otwórz Konfiguracja → Zapisz i zweryfikuj, potem wróć tu i kliknij Start.",
      );
      setView("config");
      return;
    }
    setError(null);
    try {
      const task = usePath
        ? { task_config_path: taskPath }
        : { task_description: taskDescription, signature };
      const run = await startWorkflow({ task, profile, config });
      setActiveRun(run);
      setRuns((prev) => upsertRunByCreatedAt(prev, run));
      setView("workflow");
    } catch (err) {
      const message =
        formatApiError(err) ||
        "Start workflow nie powiódł się (sprawdź backend i konfigurację).";
      setError(message);
    }
  };

  const handleStop = async () => {
    if (!activeRun) {
      setError("Brak aktywnego runa do zatrzymania.");
      return;
    }
    if (activeRun.status !== "running" && activeRun.status !== "queued") {
      setError(
        `Run ${activeRun.id.slice(0, 8)} ma status „${activeRun.status}” — Stop działa tylko dla running/queued.`,
      );
      return;
    }
    try {
      const run = await sendCommand(activeRun.id, { type: "stop" });
      setActiveRun(run);
      setRuns((prev) => upsertRunByCreatedAt(prev, run));
      setError(null);
    } catch (err) {
      const message =
        formatApiError(err) || "Stop nie powiódł się.";
      setError(message);
    }
  };

  const handleRetry = async (stageName: string) => {
    if (!activeRun) {
      return;
    }
    try {
      const run = await sendCommand(activeRun.id, {
        type: "retry_stage",
        stage_name: stageName,
        payload: retryFeedback ? { feedback: retryFeedback } : {},
      });
      setActiveRun(run);
      setRuns((prev) => upsertRunByCreatedAt(prev, run));
    } catch (err) {
      showError(err);
    }
  };

  const handleDeleteRun = async (runId: string) => {
    const label =
      runs.find((item) => item.id === runId)?.task.signature ||
      runId.slice(0, 8);
    if (!window.confirm(`Usunąć run „${label}” z historii?`)) {
      return;
    }
    setError(null);
    try {
      await deleteWorkflow(runId);
      const remaining = runs.filter((item) => item.id !== runId);
      setRuns(remaining);
      if (activeRun?.id === runId) {
        setActiveRun(remaining[0] ?? null);
        setEvents([]);
      }
    } catch (err) {
      const message =
        formatApiError(err) || "Nie udało się usunąć runa z historii.";
      setError(message);
    }
  };

  const handleBrowse = async () => {
    try {
      const files = await browseTasks(config.workspace ?? undefined);
      setBrowseFiles(files);
      if (files.length === 0) {
        setConfigFeedback({
          type: "error",
          title: "Browse — brak plików",
          details: ["Nie znaleziono plików YAML w workspace."],
        });
      } else {
        setConfigFeedback(null);
        setError(null);
      }
    } catch (err) {
      const message = formatApiError(err) || "Browse nie powiódł się.";
      setConfigFeedback({
        type: "error",
        title: "Browse nie powiódł się",
        details: [message],
      });
    }
  };

  const handlePreview = async () => {
    if (!taskPath.trim()) {
      setConfigFeedback({
        type: "error",
        title: "Preview — brak ścieżki",
        details: ["Podaj ścieżkę do pliku zadania przed Preview."],
      });
      return;
    }
    try {
      setTaskPreview(await previewTask(taskPath));
      setConfigFeedback({
        type: "success",
        title: "Podgląd zadania wczytany",
        details: [`Plik: ${taskPath}`],
      });
      setError(null);
    } catch (err) {
      const message = formatApiError(err) || "Preview nie powiódł się.";
      setConfigFeedback({
        type: "error",
        title: "Preview nie powiódł się",
        details: [message],
      });
    }
  };

  const updateConfig = (next: ConfigOverrides) => {
    setConfig(next);
    setValidated(false);
    setConfigFeedback(null);
    const saved = loadPersistedConfig();
    if (saved) {
      savePersistedConfig({ ...saved, config: next, validated: false });
    }
  };
  const updateProfile = (next: WorkflowProfile) => {
    setProfile(next);
    setValidated(false);
    const saved = loadPersistedConfig();
    if (saved) {
      savePersistedConfig({ ...saved, profile: next, validated: false });
    }
  };
  const updateTaskPath = (value: string) => {
    setTaskPath(value);
    setValidated(false);
    setConfigFeedback(null);
  };

  return {
    view,
    setView,
    config,
    updateConfig,
    profile,
    updateProfile,
    usePath,
    setUsePath: (value: boolean) => {
      setUsePath(value);
      setValidated(false);
      setConfigFeedback(null);
    },
    taskPath,
    updateTaskPath,
    signature,
    setSignature: (value: string) => {
      setSignature(value);
      setValidated(false);
    },
    taskDescription,
    setTaskDescription: (value: string) => {
      setTaskDescription(value);
      setValidated(false);
    },
    skills,
    validationWarnings,
    validated,
    taskPreview,
    browseFiles,
    setBrowseFiles,
    runs,
    activeRun,
    setActiveRun,
    events,
    stageFilter,
    setStageFilter,
    retryFeedback,
    setRetryFeedback,
    error,
    setError,
    configFeedback,
    setConfigFeedback,
    isSavingConfig,
    handleValidate,
    handleStart,
    handleStop,
    handleRetry,
    handleDeleteRun,
    handleBrowse,
    handlePreview,
  };
}
