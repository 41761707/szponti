# Szponti

Lokalny orkiestrator multi-agentowy oparty na [Cursor SDK](https://cursor.com/docs/sdk/python). Automatyzuje pipeline programistyczny: **projekt techniczny → implementacja → code review → scenariusze testowe** (opcjonalnie push do zdalnego repozytorium).

Jeden katalog `szponti` może obsługiwać wiele repozytoriów docelowych — nie trzeba kopiować orkiestratora do każdego projektu.

## Wymagania

- Python 3.11+
- Zainstalowany Cursor (lokalny bridge SDK)
- Klucz API Cursor (`CURSOR_API_KEY`) z [Dashboard → Integrations](https://cursor.com/dashboard/integrations)

## Instalacja

```powershell
cd C:\ścieżka\do\szponti
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Skopiuj szablon konfiguracji i uzupełnij wartości:

```powershell
copy env.example .env
```

Edytuj `.env` — wstaw prawdziwy klucz API i model. **Komentarze dawaj w osobnej linii** (parser nie obcina tekstu po `#`):

```dotenv
CURSOR_API_KEY=cursor_twoj_klucz
AGENT_MODEL=composer-2.5
# alternatywnie: AGENT_MODEL=auto
```

## Architektura: orkiestrator vs workspace

| Warstwa | Opis | Ścieżka |
|---|---|---|
| **Orkiestrator** | Kod Pythona (`AgentOrchestrator.py`, `tools.py`, skille workflow) | katalog `szponti/` |
| **Workspace agentów** | Repo, w którym agenci czytają kod, robią zmiany i commity | `AGENT_WORKSPACE_DIR` lub `--workspace` |

Agenci uruchamiają się z `cwd` ustawionym na workspace docelowy i ładują reguły projektu (`.cursor/rules`) z tego repozytorium. Skille workflow (develop, CR, tech-project itd.) są wstrzykiwane do prompta z osobnej ścieżki (`MCP_TOOLS_SKILLS_DIR`).

## Konfiguracja

### Pliki środowiskowe

Przy starcie `resolve_config` ładuje pliki w kolejności (pierwszy ustawiony klucz wygrywa):

1. `<workspace>/.env`
2. `<katalog szponti>/.env` — wspólne sekrety i centralne skille
3. `<workspace>/.szponti.env` — ustawienia specyficzne dla repo docelowego

Alternatywnie: jawny plik przez `--env-file`.

### Zmienne środowiskowe

| Zmienna | Wymagana | Domyślnie | Opis |
|---|---|---|---|
| `CURSOR_API_KEY` | tak | — | Klucz API Cursor |
| `AGENT_MODEL` | tak | — | Model agenta, np. `composer-2.5` lub `auto` |
| `AGENT_WORKSPACE_DIR` | nie* | katalog z `--workspace` lub wykryty | Root repo, w którym pracują agenci |
| `MCP_TOOLS_SKILLS_DIR` | nie | `<workspace>/.cursor/skills` | Katalog ze skillami workflow |
| `MCP_TOOLS_MCP_CONFIG_FILE` | nie | `<workspace>/.cursor/mcp.json` | Konfiguracja MCP (db-context) |
| `SZPONTI_STATE_DIR` | nie | `<workspace>/.szponti` | Cache i logi runów |

\* Wymagana pośrednio — ustawiana automatycznie z `--workspace` albo wykrywania katalogu z `.git`.

### Przykład: jeden szponti, wiele repozytoriów

**`szponti/.env`** (wspólny, trzymany w jednym miejscu):

```dotenv
CURSOR_API_KEY=cursor_...
AGENT_MODEL=composer-2.5

MCP_TOOLS_SKILLS_DIR=C:\Users\Radek\Desktop\Projekty\szponti\.cursor\skills
MCP_TOOLS_MCP_CONFIG_FILE=C:\Users\Radek\Desktop\Projekty\szponti\.cursor\mcp.json
```

**`EkstraBet/.szponti.env`** (per repo docelowe):

```dotenv
AGENT_WORKSPACE_DIR=C:\Users\Radek\Desktop\Projekty\EkstraBet
SZPONTI_STATE_DIR=C:\Users\Radek\Desktop\Projekty\EkstraBet\.szponti
```

Uruchomienie:

```powershell
cd C:\Users\Radek\Desktop\Projekty\szponti

python AgentOrchestrator.py `
  --workspace C:\Users\Radek\Desktop\Projekty\EkstraBet `
  --env-file C:\Users\Radek\Desktop\Projekty\EkstraBet\.szponti.env `
  C:\Users\Radek\Desktop\Projekty\EkstraBet\tasks\EB-123.yaml
```

### Przykład: praca w tym samym repo (szponti = workspace)

Jeśli testujesz na samym repozytorium szpontiego, wystarczy `.szponti.env`:

```dotenv
AGENT_WORKSPACE_DIR=C:\Users\Radek\Desktop\Projekty\szponti
SZPONTI_STATE_DIR=C:\Users\Radek\Desktop\Projekty\szponti\.szponti
```

```powershell
python AgentOrchestrator.py --env-file .szponti.env task_config.yaml
```

## Opis zadania (`task_config.yaml`)

Plik YAML z sygnaturą zadania i opisem wymagań biznesowych:

```yaml
signature: EB-123

task_description: |
  Dodaj endpoint GET /api/users/{id} zwracający profil użytkownika.
  Uwzględnij walidację ID i obsługę 404.
```

Obsługiwane klucze (polskie aliasy działają tak samo):

| Angielski | Polski |
|---|---|
| `signature` | `sygnatura` |
| `task_description` | `opis` |

## Uruchomienie

```powershell
python AgentOrchestrator.py [opcje] <ścieżka_do_task_config.yaml>
```

### Opcje CLI

| Opcja | Opis |
|---|---|
| `task_input` | Ścieżka do pliku `task_config.yaml` |
| `--workspace PATH` | Root repozytorium docelowego (nadpisuje wykrywanie workspace) |
| `--env-file PATH` | Jawny plik env (np. `.szponti.env` w repo klienta) |
| `--push` | Dołącz etap git-push na końcu workflow |

## Pipeline workflow

```
tech-project  →  [akceptacja człowieka]  →  develop ⇄ CR  →  scenariusze-testowe  →  [opcjonalnie git-push]
                      ↑                           ↑
                 db-context                  db-context
              (gdy POTRZEBNE_DANE)        (gdy POTRZEBNE_DANE)
```

### Etapy

1. **tech-project** — agent generuje projekt techniczny na podstawie opisu zadania. Po każdej iteracji orkiestrator pyta w konsoli o akceptację lub poprawki.
2. **db-context** — uruchamiany automatycznie, gdy agent zgłosi `DB_STATUS: POTRZEBNE_DANE` (odczyt danych z bazy przez MCP).
3. **develop** — implementacja zgodnie z zaakceptowanym projektem technicznym.
4. **cr** — code review implementacji. Agent kończy statusem `CR_STATUS: OK` lub `CR_STATUS: POPRAWKI`. Przy poprawkach pętla develop/CR powtarza się.
5. **scenariusze-testowe** — generowanie/weryfikacja testów i scenariuszy QA.
6. **git-push** (opcjonalny) — commit i push zmian (wymaga jawnego potwierdzenia w kodzie workflow).

### Interakcja człowieka

**Akceptacja projektu technicznego** — po wygenerowaniu wpisz w konsoli np.:

- akceptacja: `akceptuj`, `gotowy`, `projekt ok`, `realizuj`
- poprawki: `popraw ...`, `niegotowy`, `odrzuc`

**Statusy agentów** (w ostatnich liniach outputu):

```
CR_STATUS: OK
CR_STATUS: POPRAWKI
DB_STATUS: POTRZEBNE_DANE
```

## Skille

Skille workflow leżą w `.cursor/skills/` i są ładowane do prompta przez `tools.py`:

| Skill | Rola |
|---|---|
| `tech-project` | Projekt techniczny |
| `develop` | Implementacja |
| `cr` | Code review |
| `scenariusze-testowe` | Testy i scenariusze QA |
| `db-context` | Kontekst z bazy danych (MCP) |
| `git-push` | Commit i push |
| `caveman` | Tryb zwięzłej komunikacji (prefiks `/caveman` przy każdym runie) |

Ścieżkę skilli ustawiasz przez `MCP_TOOLS_SKILLS_DIR` — może wskazywać na centralny katalog szpontiego, niezależnie od repo docelowego.

## MCP i baza danych

Konfiguracja MCP: `.cursor/mcp.json` (ścieżka przez `MCP_TOOLS_MCP_CONFIG_FILE`).

Przykład serwera read-only:

```json
{
  "mcpServers": {
    "ekstrabet-mysql-readonly": {
      "type": "stdio",
      "command": "python",
      "args": ["mcp_servers/mysql_readonly_server.py"],
      "envFile": "C:/ścieżka/do/repo/.env.cursor-mcp"
    }
  }
}
```

Ścieżki w `mcp.json` (skrypt serwera, `envFile`) odnoszą się do **repo docelowego** (`AGENT_WORKSPACE_DIR`), nie do katalogu szpontiego. Upewnij się, że skrypt MCP i plik `.env.cursor-mcp` istnieją w projekcie, nad którym pracujesz.

## Web UI (FastAPI + React)

Panel do wyboru etapów, konfiguracji i podglądu runów na żywo (SSE).

```powershell
# backend
uvicorn web.backend.app:app --reload --port 8000

# frontend (osobny terminal)
cd web\frontend
npm install
npm run dev
```

Szczegóły i profile etapów: [web/README.md](web/README.md).

## Struktura katalogów

```
szponti/
├── AgentOrchestrator.py   # CLI i orkiestracja workflow
├── config.py              # Rozwiązywanie konfiguracji i .env
├── workflow_models.py     # Profile, eventy, statusy runów
├── tools.py               # Budowanie promptów ze skilli
├── task_loader.py         # Wczytywanie task_config.yaml
├── web/
│   ├── backend/           # FastAPI (REST + SSE)
│   └── frontend/          # React/Vite dashboard
├── tests/
├── requirements.txt
├── pyproject.toml
├── env.example            # Szablon .env (bez sekretów)
├── .szponti.env           # Przykład workspace dla tego repo
├── task_config.yaml       # Przykład zadania
├── .env                   # Sekrety (gitignore — nie commituj)
├── .cursor/
│   ├── skills/            # Skille workflow
│   └── mcp.json           # Konfiguracja MCP
└── .szponti/              # Stan runtime (cache, runy) — tworzy się automatycznie
```

## Rozwiązywanie problemów

| Problem | Co sprawdzić |
|---|---|
| `Environment variable CURSOR_API_KEY is not set` | Uzupełnij `.env` w katalogu szponti |
| `Skill not found: ...` | `MCP_TOOLS_SKILLS_DIR` wskazuje właściwy katalog; nazwa folderu = nazwa skilla (np. `tech-project`) |
| Agent pracuje w złym repo | Ustaw `--workspace` lub `AGENT_WORKSPACE_DIR` w `.szponti.env` |
| MCP / db-context nie działa | Sprawdź `.cursor/mcp.json`, istnienie skryptu serwera i `.env.cursor-mcp` w repo docelowym |
| Model nieprawidłowy | Nie dodawaj komentarza inline przy wartości w `.env` (`AGENT_MODEL=auto #...` — parser wczyta całość) |
| `CursorAgentError` przy starcie | Klucz API, dostęp do Cursor, czy bridge lokalny jest dostępny |

## Moduły

| Plik | Odpowiedzialność |
|---|---|
| `AgentOrchestrator.py` | Pętle workflow, uruchamianie agentów Cursor SDK, interakcja z konsolą |
| `config.py` | Wczytywanie `.env`, domyślne ścieżki, `SzpontiConfig` |
| `tools.py` | Składanie promptów etapów ze skilli i kontekstu zadania |
| `task_loader.py` | Parsowanie `task_config.yaml` |
