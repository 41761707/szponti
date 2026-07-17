# Web UI — uruchamianie lokalne

## Backend

```powershell
cd C:\ścieżka\do\szponti
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_web.py
```

albo:

```powershell
uvicorn web.backend.app:app --port 8000
```

**Windows:** nie używaj `--reload` — wymusza `SelectorEventLoop`, który nie umie odpalić subprocessu Cursor bridge (`NotImplementedError`).

Healthcheck: `GET http://127.0.0.1:8000/api/health`

## Frontend

```powershell
cd web\frontend
npm install
npm run dev
```

UI: `http://127.0.0.1:5173` (proxy `/api` -> backend `:8000`)

## Profile etapów

| Preset | Etapy | Wymagane stage_inputs |
|---|---|---|
| `full` | tech-project, develop, cr, scenariusze-testowe, db-context | — |
| `develop_cr` | develop, cr, db-context | `tech-project` |
| `cr_only` | cr, db-context | `develop` |
| `techproject_only` | tech-project, db-context | — |

Etap `db-context` można włączyć lub wyłączyć w profilu (checkbox). Gdy wyłączony, linia `DB_STATUS: POTRZEBNE_DANE` w outputcie agenta nie uruchamia odczytu bazy przez MCP. `git-push` wymaga `authorize_push=true`.
