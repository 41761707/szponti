from __future__ import annotations

import re 
from dataclasses import dataclass
from pathlib import Path

from config import SzpontiConfig

WORK_PACKAGES_HEADERS = "## Paczki pracy"
WORK_PACKAGE_TAG_PATTERN = re.compile(r"\[(SQL|PYTHON)\]", re.IGNORECASE)

@dataclass(frozen=True)
class ToolResult:
    "Tool output passed to the orchestrator stage runner"
    tool_name: str
    prompt: str
    requires_human_confirmation: bool = False

def extract_work_packages(techproject_result: str | None) -> str | None:
    """Extract work packages section from accepted tech project output"""
    if not techproject_result:
        return None
    
    lines = techproject_result.splitlines()
    start_index = None
    for index, line in enumerate(lines):
        if line.strip().casefold() == WORK_PACKAGES_HEADERS.casefold():
            start_index = index
            break
    if start_index is None:
        return None
    
    section_lines: list[str] = []
    for line in lines[start_index + 1:]:
        if line.startswith("## ") and section_lines:
            break
        section_lines.append(line)
    
    section = "\n".join(section_lines).strip()
    if not section:
        return None
    if not WORK_PACKAGE_TAG_PATTERN.search(section):
        return None
    return section

class Tools:
    """Build workflow stage prompts from repository skills"""
    
    def __init__(self, config: SzpontiConfig) -> None:
        self.skills_path = config.skills_dir
        self.mcp_config_path = config.mcp_config_file

    def load_skill(self, skill_name: str) -> str:
        """Load skill instructions from configurated skills directory"""
        skill_path = self.skills_path / skill_name / "SKILL.md"
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill not found: {skill_path}")
        return skill_path.read_text(encoding="utf-8")
    
    def list_available_skills(self) -> list[str]:
        """Return locally avaiable skill directory names"""
        if not self.skills_path.exists():
            return []
        return sorted(
            path.name
            for path in self.skills_path.iterdir()
            if path.is_dir() and (path / "SKILL.md").exists())
    
    def prepare_techproject(
        self,
        task_descrption,
        signature,
        review_feedback=None,
        previous_result=None):
        """Build promt for technical project stage"""
        instruction = (
            "Pracujesz jako agent tworzący projekt techniczny zadania. Twoim zadaniem jest wygenerowanie projektu technicznego."
            "Projekt techniczny opisuje, w jaki sposób zrealizować wymagania biznesowe zadania. Nie twórz kodu ani nie implementuj go, jedynie przedstaw jak zrobić zadanie.")
        if review_feedback:
            instruction += f"\n\nFeedback użytkownika:\n{review_feedback.strip()}"
        return ToolResult(
            tool_name="prepare_techproject",
            prompt=self.build_skill_prompt(
                "tech-project",
                instruction,
                task_descrption,
                signature,
                previous_result))

    def run_develop(
        self,
        task_descrption,
        signature,
        techproject_result = None,
        cr_feedback = None,
    ) -> ToolResult:
        """Build prompt for implementation stage"""
        instruction = ""
        previous_result = ""
        work_packages = None
        if cr_feedback:
            instruction = (
                "Pracujesz jako agent develop."
                "Popraw implementacje zgodnie z feedbackiem CR."
                "Zachowaj założenia zaakceptowanego projektu technicznego.")
            previous_result = "\n\n".join(
                part.strip() 
                for part in [
                    f"Zaakceptowany projekt techniczny:\n{techproject_result.strip()}",
                    f"Feedback CR:\n{cr_feedback.strip()}"] 
                if part.strip())
        else:
            work_packages = extract_work_packages(techproject_result)
            instruction_parts = [
                "Pracujesz jako agent implementujący projekt techniczny zadania (develop). Twoim zadaniem jest implementacja projektu technicznego.",
                "Wykonaj implementacje zgodnie ze skillem develop. Traktuj zaakceptowany projekt techniczny jako podstawowy kontakt."]
            if work_packages:
                instruction_parts.extend([
                    "Realizuj paczki pract z projekt technicznego po kolei.",
                    "Każda linia z tagiem [SQL] lub [PYTHON] opisuje zadanie do wykonania.",
                    "Są to osobne paczki do wykonania przed zamknięciem etapu"])
            instruction = "\n".join(instruction_parts)
            previous_result = techproject_result
        prompt = self.build_skill_prompt(
            "develop",
            instruction,
            task_descrption,
            signature,
            previous_result)
        if work_packages:
            prompt = f"{prompt}\n\nPaczki pracy z TechProject:\n{work_packages}"
        return ToolResult(tool_name="run_develop", prompt=prompt)

    def continue_develop(self, cr_feedback: str = "", db_context: str = "") -> ToolResult:
        """Build short continuation prompt for persistent develop agent"""
        parts = ["Kontynuuj implementacje w tej samej rozmowie"]
        if cr_feedback:
            parts.extend(["", "Feedback CR:", cr_feedback.strip()])
        if db_context:
            parts.extend(["", "Kontekst bazy danych:", db_context.strip()])
        return ToolResult(tool_name="run_develop", prompt="\n".join(parts))

    def run_cr(self, task_descrption, signature, develop_result = None) -> ToolResult:
        """Build prompt for code review stage"""
        instruction = "\n".join([
            "Pracujesz jako agent CR.",
            "Wykonaj CR zmian zgodnie ze skillem CR.",
            "Oceniaj aktualny stan repozytorium, diff i przekazany wynik z develop."])
        return ToolResult(
            tool_name="run_cr",
            prompt=self.build_skill_prompt(
                "cr",
                instruction,
                task_descrption,
                signature,
                develop_result))

    def continue_cr(self, develop_result = "", db_context = "") -> ToolResult:
        """Build short continuation prompt for persistent CR agent"""
        parts = ["Kontynuuj CR w tej samej rozmowie",
                    "Oceniaj aktualny stan repozytorium i zakończ statusem",
                    "CR_STATUS: OK albo CR_STATUS: POPRAWKI"]
        if develop_result:
            parts.extend(["", "Wynik z develop:", develop_result.strip()])
        if db_context:
            parts.extend(["", "Kontekst bazy danych:", db_context.strip()])
        return ToolResult(tool_name="run_cr", prompt="\n".join(parts))

    def run_test_scenarios(self, task_descrption, signature, cr_result = None) -> ToolResult:
        """Build prompt for test scenarios stage"""
        instruction = "\n".join([
            "Pracujesz jako agent testujący scenariusze.",
            "Wykonaj test scenariusze zgodnie ze skillem scenariusze-testowe."])
        return ToolResult(
            tool_name="run_test_scenarios",
            prompt=self.build_skill_prompt(
                "scenariusze-testowe",
                instruction,
                task_descrption,
                signature,
                cr_result))
    
    def run_db_context(self, task_descrption, signature, question, previous_result) -> ToolResult:
        """Build prompt for MCP database context stage"""
        if self.mcp_config_path.exists():
            mcp_status = f"MCP config ok: {self.mcp_config_path}"
        else:
            mcp_status = "MCP config not found"
        instruction_parts = [
            "Pracujesz jako agent db-context.",
            "Zbierz brakujący kontekst z bazy danych przez MCP ekstrabet-mysql-readonly",
            "Jeśli MCP nie jest dostępny, wypisz potrzebne query i zgłośc blokadę dalszej realizacji",
            mcp_status]
        if question:
            instruction_parts.extend(["", "Pytanie do bazy danych:", question.strip()])
        else:
            instruction_parts.append("Zakres brakujących danych ustal na podstawie wyniku poprzedniego etapu")
        return ToolResult(
            tool_name="run_db_context",
            prompt=self.build_skill_prompt(
                "db-context",
                "\n".join(instruction_parts),
                task_descrption,
                signature,
                previous_result))

    def prepare_git_push(self, task_descrption, signature, cr_result, human_confirmation) -> ToolResult:
        """Build git-push prompt with optional human confirmation"""
        if not human_confirmation:
            return ToolResult(
                tool_name="prepare_git_push",
                prompt="Etap git-push wymaga jawnego potwierdzenia użytkownika. Nie uruchamiaj commita ani pusha bez potwierdzenia.",
                requires_human_confirmation=True)
        return ToolResult(
            tool_name="prepare_git_push",
            prompt=self.build_skill_prompt(
                "git-push",
                "Użyj workflow git-push. Commit i push są dozwolone",
                task_descrption,
                signature,
                cr_result))

    def build_skill_prompt(self, skill_name: str, instruction: str, task_descrption: str, signature: str, previous_result: str) -> str:
        """Assemble final prompt for Cursor agent stage"""
        skill = self.load_skill(skill_name)
        parts = [
            f"Użyj skilla {skill_name} do realizacji zadania:",
            "Tryb multiagentowy:",
            "Jesteś osobnym agentem wyspecjalizowanym w tym jednym etapie",
            "Nie masz wspólnej historii rozmowy z innymi agentami",
            "Korzystaj wyłącznie z opisu zadania, sygnatury , treści skilla i aktualnego repozytorium oraz jawnie przekazanego kontekstu poniżej",
            "Kontekst bazy danych:",
            "Jeśli do wykonania etapu potrzebujesz danych z bazy danych jawnie zgłoś to przez dodanie osobnej linii",
            "DB_STATUS: POTRZEBNE_DANE",
            "Jeśli jej nie dodasz, orkiestrator uzna, że nie potrzebujesz danych z bazy danych i przejdzie dalej",
            "Instrukcja etapu:",
            instruction,
            "Sygnatura:",
            signature or "BRAK",
            "Opis zadania:",
            task_descrption.strip(),
            "Treść skilla:",
            skill.strip()]
        if previous_result:
            parts.extend(["", "Wynik poprzedniego etapu:", previous_result.strip()])
        return "\n".join(parts)
