from pathlib import Path

import pytest

from llm_court.config import ModelsConfig, load_models_config
from llm_court.llm import PromptLoader

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def models_config() -> ModelsConfig:
    return load_models_config(BACKEND_ROOT / "config" / "models.yaml")


@pytest.fixture
def prompts() -> PromptLoader:
    return PromptLoader(BACKEND_ROOT / "prompts")
