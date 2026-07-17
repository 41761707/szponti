import { ConfigPanel } from "@/components/ConfigPanel";
import { FailureBanner } from "@/components/FailureBanner";
import { RunLog } from "@/components/RunLog";
import { StageCard } from "@/components/StageCard";
import { StageSelector } from "@/components/StageSelector";
import {
  RunSidebar,
  WorkflowActions,
} from "@/components/WorkflowChrome";
import { WorkflowTimeline } from "@/components/WorkflowTimeline";
import { useDashboardState } from "@/hooks/useDashboardState";

export function App() {
  const state = useDashboardState();
  const latestStage =
    state.activeRun && state.activeRun.stages.length > 0
      ? state.activeRun.stages[state.activeRun.stages.length - 1]
      : null;

  return (
    <div className="app-shell">
      <RunSidebar
        runs={state.runs}
        activeRunId={state.activeRun?.id ?? null}
        view={state.view}
        onViewChange={state.setView}
        onSelectRun={(run) => {
          state.setActiveRun(run);
          state.setView("workflow");
        }}
        onDeleteRun={(runId) => void state.handleDeleteRun(runId)}
      />
      <main className="main">
        {state.error ? (
          <div className="banner error">
            <span>{state.error}</span>
            <button type="button" onClick={() => state.setError(null)}>
              Zamknij
            </button>
          </div>
        ) : null}
        {state.view === "config" ? (
          <ConfigPanel
            config={state.config}
            taskPath={state.taskPath}
            signature={state.signature}
            taskDescription={state.taskDescription}
            usePath={state.usePath}
            skills={state.skills}
            validationWarnings={state.validationWarnings}
            taskPreview={state.taskPreview}
            browseFiles={state.browseFiles}
            feedback={state.configFeedback}
            isSaving={state.isSavingConfig}
            onConfigChange={state.updateConfig}
            onTaskPathChange={state.updateTaskPath}
            onSignatureChange={state.setSignature}
            onDescriptionChange={state.setTaskDescription}
            onUsePathChange={state.setUsePath}
            onSave={() => void state.handleValidate()}
            onPreview={() => void state.handlePreview()}
            onBrowse={() => void state.handleBrowse()}
            onSelectBrowseFile={(path) => {
              state.updateTaskPath(path);
              state.setBrowseFiles([]);
            }}
            onDismissFeedback={() => state.setConfigFeedback(null)}
          />
        ) : (
          <>
            <StageSelector
              profile={state.profile}
              onChange={state.updateProfile}
            />
            <WorkflowActions
              canStart={state.validated}
              canStop={
                Boolean(state.activeRun) &&
                (state.activeRun?.status === "running" ||
                  state.activeRun?.status === "queued")
              }
              retryFeedback={state.retryFeedback}
              onStart={() => void state.handleStart()}
              onStop={() => void state.handleStop()}
              onRetryFeedbackChange={state.setRetryFeedback}
            />
            {state.activeRun ? (
              <>
                <FailureBanner
                  status={state.activeRun.status}
                  events={state.events}
                  stages={state.activeRun.stages}
                />
                <WorkflowTimeline
                  profile={state.activeRun.profile}
                  stages={state.activeRun.stages}
                  status={state.activeRun.status}
                />
                <div className="stage-grid">
                  {state.activeRun.stages.map((stage) => (
                    <StageCard
                      key={`${stage.name}-${stage.run_id ?? stage.started_at}`}
                      stage={stage}
                      canRetry={[
                        "failed",
                        "needs_changes",
                        "completed",
                      ].includes(stage.status)}
                      onRetry={(name) => void state.handleRetry(name)}
                    />
                  ))}
                </div>
                {latestStage ? (
                  <section className="panel">
                    <h2>Aktualny wynik</h2>
                    <StageCard stage={latestStage} />
                  </section>
                ) : null}
                <RunLog
                  events={state.events}
                  stageFilter={state.stageFilter}
                  onFilterChange={state.setStageFilter}
                />
              </>
            ) : null}
          </>
        )}
      </main>
    </div>
  );
}
