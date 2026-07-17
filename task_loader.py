from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml 

@dataclass(frozen=True)
class TaskConfig:
    """Task configuration"""
    signature: str
    task_description: str

def load_task_config(config_file: Path) -> TaskConfig:
    """Load task configuration from YAML file
    Supports keys: signature/sygnatura, task_description/opis
    """

    if not config_file.exists():
        raise FileNotFoundError(f"Plik konfiguracyjny nie znaleziony: {config_file}")
    try:
        content = config_file.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise RuntimeError(f"Błąd podczas analizy pliku YAML: {e}")
    if not isinstance(data, dict):
        raise RuntimeError(f"Nieprawidłowy format pliku YAML: {config_file}")

    signature = data.get("signature") or data.get("sygnatura")
    task_description = data.get("task_description") or data.get("opis")
    if not isinstance(signature, str) or not signature.strip():
        raise RuntimeError(f"Nieprawidłowa sygnatura: {signature}")
    if not isinstance(task_description, str) or not task_description.strip():
        raise RuntimeError(f"Nieprawidłowy opis zadania: {task_description}")
    return TaskConfig(signature=signature.strip(), task_description=task_description.strip())

def _is_yaml_path(path: Path) -> bool:
    """Check if path is a YAML file"""
    suffix = path.suffix.lower()
    return suffix in (".yaml", ".yml")

def resolve_task_input(
    task_input: str | None) -> TaskConfig:
    """Resolve task input from command line or YAML file"""
    if not task_input:
        raise RuntimeError("Podaj zadanie wraz z sygnatura lub plik konfiguracyjny")
    input_path = Path(task_input)
    if input_path.exists() and input_path.is_file() and _is_yaml_path(input_path):
        return load_task_config(input_path.resolve())
    raise RuntimeError(f"Nieprawidłowy format wejścia: {task_input}. Użyj sygnatury zadania lub pliku konfiguracyjnego")