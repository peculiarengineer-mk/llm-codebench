"""Configuration loading for llm-codebench.

Single responsibility: turn environment + ``config/models.yaml`` + CLI overrides
into the shared value objects from :mod:`bench.types`. No network, no business
logic. ``dotenv.load_dotenv()`` runs at import time so ``OPENROUTER_API_KEY`` is
available to any module that imports this one.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from bench.types import ModelSpec, RunConfig

# Load .env from the project root (and cwd) at import time.
load_dotenv()

# Project root = the directory containing the `bench` package's parent.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS_YAML = PROJECT_ROOT / "config" / "models.yaml"

# RunConfig defaults (overridable via the CLI in T8).
DEFAULT_K = 3
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_SPEND_USD = 5.0
DEFAULT_PROMPT_STYLE = "strict"

_API_KEY_ENV = "OPENROUTER_API_KEY"


def get_api_key() -> str:
    """Return the OpenRouter API key, or raise a friendly error if unset."""
    key = os.environ.get(_API_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{_API_KEY_ENV} is not set. Copy .env.example to .env and add your "
            "OpenRouter API key, or export it in your shell."
        )
    return key


def load_model_specs(path: str | Path | None = None) -> list[ModelSpec]:
    """Parse ``config/models.yaml`` into a list of :class:`ModelSpec`.

    Accepts either a top-level ``models:`` mapping (list of entries) or a bare
    top-level list. Each entry may be a plain string id or a mapping with ``id``
    and optional ``price_override``.
    """
    yaml_path = Path(path) if path is not None else DEFAULT_MODELS_YAML
    if not yaml_path.exists():
        raise FileNotFoundError(f"Models config not found: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if isinstance(data, dict):
        raw_entries = data.get("models", [])
    elif isinstance(data, list):
        raw_entries = data
    else:
        raise ValueError(
            f"{yaml_path}: expected a mapping with 'models:' or a list, "
            f"got {type(data).__name__}"
        )

    if not raw_entries:
        raise ValueError(f"{yaml_path}: no models defined")

    specs: list[ModelSpec] = []
    for entry in raw_entries:
        if isinstance(entry, str):
            specs.append(ModelSpec(id=entry))
        elif isinstance(entry, dict):
            model_id = entry.get("id")
            if not model_id:
                raise ValueError(f"{yaml_path}: model entry missing 'id': {entry!r}")
            specs.append(
                ModelSpec(id=model_id, price_override=entry.get("price_override"))
            )
        else:
            raise ValueError(
                f"{yaml_path}: model entry must be a string or mapping, "
                f"got {type(entry).__name__}"
            )
    return specs


def build_run_config(
    *,
    models: list[str] | None = None,
    k: int | None = None,
    temperature: float | None = None,
    timeout: float | None = None,
    max_spend_usd: float | None = None,
    dry_run: bool = False,
    prompt_style: str | None = None,
    models_yaml: str | Path | None = None,
) -> RunConfig:
    """Build a :class:`RunConfig` from CLI-supplied overrides with sane defaults.

    ``models`` defaults to every id in ``config/models.yaml`` when not supplied.
    All other fields fall back to the module-level ``DEFAULT_*`` constants.
    """
    if not models:
        models = [spec.id for spec in load_model_specs(models_yaml)]

    style = prompt_style or DEFAULT_PROMPT_STYLE
    if style not in ("strict", "loose"):
        raise ValueError(f"prompt_style must be 'strict' or 'loose', got {style!r}")

    return RunConfig(
        models=list(models),
        k=k if k is not None else DEFAULT_K,
        temperature=temperature if temperature is not None else DEFAULT_TEMPERATURE,
        timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        max_spend_usd=(
            max_spend_usd if max_spend_usd is not None else DEFAULT_MAX_SPEND_USD
        ),
        dry_run=dry_run,
        prompt_style=style,  # type: ignore[arg-type]
    )
