import { useState } from "react";

import type { ConfigOverrides, TaskConfig } from "@/types";

export type ConfigFeedback =
  | { type: "success"; title: string; details: string[] }
  | { type: "error"; title: string; details: string[] }
  | null;

interface ConfigPanelProps {
  config: ConfigOverrides;
  taskPath: string;
  signature: string;
  taskDescription: string;
  usePath: boolean;
  skills: string[];
  validationWarnings: string[];
  taskPreview: TaskConfig | null;
  browseFiles: string[];
  feedback: ConfigFeedback;
  isSaving: boolean;
  onConfigChange: (next: ConfigOverrides) => void;
  onTaskPathChange: (value: string) => void;
  onSignatureChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onUsePathChange: (value: boolean) => void;
  onSave: () => void;
  onPreview: () => void;
  onBrowse: () => void;
  onSelectBrowseFile: (path: string) => void;
  onDismissFeedback: () => void;
}

export function ConfigPanel({
  config,
  taskPath,
  signature,
  taskDescription,
  usePath,
  skills,
  validationWarnings,
  taskPreview,
  browseFiles,
  feedback,
  isSaving,
  onConfigChange,
  onTaskPathChange,
  onSignatureChange,
  onDescriptionChange,
  onUsePathChange,
  onSave,
  onPreview,
  onBrowse,
  onSelectBrowseFile,
  onDismissFeedback,
}: ConfigPanelProps) {
  const [showApiKey, setShowApiKey] = useState(false);

  const setField = (key: keyof ConfigOverrides, value: string) => {
    onConfigChange({ ...config, [key]: value || null });
  };

  return (
    <section className="panel config-panel">
      <h2>Konfiguracja</h2>
      <p className="muted config-hint">
        Wpisz ścieżki i model, potem kliknij &quot;Zapisz i zweryfikuj&quot;.
        Dane zostaną zapisane w przeglądarce i użyte przy starcie workflow.
      </p>
      {feedback ? (
        <div
          className={
            feedback.type === "success"
              ? "config-feedback success"
              : "config-feedback error"
          }
          role="status"
        >
          <div className="config-feedback-header">
            <strong>{feedback.title}</strong>
            <button type="button" onClick={onDismissFeedback}>
              Zamknij
            </button>
          </div>
          {feedback.details.length > 0 ? (
            <ul>
              {feedback.details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div className="field-row">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={usePath}
            onChange={(event) => onUsePathChange(event.target.checked)}
          />
          <span>Użyj pliku zadania (YAML)</span>
        </label>
      </div>
      {usePath ? (
        <div className="field-stack">
          <label>
            Plik zadania
            <div className="inline-actions">
              <input
                value={taskPath}
                onChange={(event) => onTaskPathChange(event.target.value)}
                placeholder="path/to/task_config.yaml"
              />
              <button type="button" onClick={onBrowse}>
                Browse
              </button>
              <button type="button" onClick={onPreview}>
                Preview
              </button>
            </div>
          </label>
          {browseFiles.length > 0 ? (
            <ul className="browse-list">
              {browseFiles.map((file) => (
                <li key={file}>
                  <button type="button" onClick={() => onSelectBrowseFile(file)}>
                    {file}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {taskPreview ? (
            <pre className="preview-box">
              {taskPreview.signature}
              {"\n"}
              {taskPreview.task_description}
            </pre>
          ) : null}
        </div>
      ) : (
        <div className="field-stack">
          <label>
            Sygnatura
            <input
              value={signature}
              onChange={(event) => onSignatureChange(event.target.value)}
            />
          </label>
          <label>
            Opis zadania
            <textarea
              rows={5}
              value={taskDescription}
              onChange={(event) => onDescriptionChange(event.target.value)}
            />
          </label>
        </div>
      )}
      <div className="field-grid">
        <label>
          Env file
          <input
            value={config.env_file ?? ""}
            onChange={(event) => setField("env_file", event.target.value)}
          />
        </label>
        <label>
          Skills dir
          <input
            value={config.skills_dir ?? ""}
            onChange={(event) => setField("skills_dir", event.target.value)}
          />
        </label>
        <label>
          MCP config
          <input
            value={config.mcp_config_file ?? ""}
            onChange={(event) => setField("mcp_config_file", event.target.value)}
          />
        </label>
        <label>
          Model
          <input
            value={config.model ?? ""}
            onChange={(event) => setField("model", event.target.value)}
            placeholder="composer-2.5"
          />
        </label>
        <label className="api-key-field">
          API key
          <div className="secret-field">
            <input
              type={showApiKey ? "text" : "password"}
              autoComplete="off"
              value={config.api_key ?? ""}
              onChange={(event) => setField("api_key", event.target.value)}
            />
            <button
              type="button"
              className="secret-toggle"
              onClick={() => setShowApiKey((prev) => !prev)}
            >
              {showApiKey ? "UKRYJ" : "POKAŻ"}
            </button>
          </div>
        </label>
        <label>
          Workspace
          <input
            value={config.workspace ?? ""}
            onChange={(event) => setField("workspace", event.target.value)}
          />
        </label>
      </div>
      <div className="inline-actions">
        <button
          type="button"
          className="primary"
          onClick={onSave}
          disabled={isSaving}
        >
          {isSaving ? "Zapisywanie…" : "Zapisz i zweryfikuj"}
        </button>
      </div>
      {validationWarnings.length > 0 ? (
        <ul className="warning-list">
          {validationWarnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {skills.length > 0 ? (
        <p className="muted">Skills: {skills.join(", ")}</p>
      ) : null}
    </section>
  );
}
