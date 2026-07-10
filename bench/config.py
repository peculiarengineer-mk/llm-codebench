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

from bench.types import (
    VALID_EFFORTS,
    ModelSpec,
    RunConfig,
    RunTarget,
    target_label,
)

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
            efforts = _validate_efforts(entry.get("efforts"), where=f"{yaml_path}: {model_id}")
            specs.append(
                ModelSpec(
                    id=model_id,
                    price_override=entry.get("price_override"),
                    efforts=efforts,
                )
            )
        else:
            raise ValueError(
                f"{yaml_path}: model entry must be a string or mapping, "
                f"got {type(entry).__name__}"
            )
    return specs


def _validate_efforts(raw: object, *, where: str) -> list[str] | None:
    """Normalize a raw ``efforts`` value (from YAML or CLI) to a checked list.

    Accepts ``None`` (→ ``None``), a single string, or a list of strings. Every
    level must be one of :data:`~bench.types.VALID_EFFORTS`; order is preserved
    and duplicates are dropped so a sweep stays deterministic.
    """
    if raw is None:
        return None
    values = [raw] if isinstance(raw, str) else list(raw)
    seen: list[str] = []
    for value in values:
        level = str(value).strip().lower()
        if level not in VALID_EFFORTS:
            valid = ", ".join(VALID_EFFORTS)
            raise ValueError(f"{where}: invalid effort {value!r} (valid: {valid})")
        if level not in seen:
            seen.append(level)
    return seen or None


def expand_targets(
    specs: list[ModelSpec], *, efforts_override: list[str] | None = None
) -> list[RunTarget]:
    """Fan out model specs into resolved :class:`RunTarget` benchmark targets.

    Each spec with ``efforts`` (or the run-wide ``efforts_override``, which wins
    for every model) yields one target per effort level; a spec with no efforts
    yields a single effort-less target. Labels come from
    :func:`~bench.types.target_label`, so a model swept across levels shows up as
    distinct leaderboard rows.
    """
    targets: list[RunTarget] = []
    seen: set[str] = set()
    for spec in specs:
        levels: list[str | None]
        # A non-empty override wins for every model; an empty list (or None) means
        # "no override" so per-spec efforts apply — an empty override must not
        # silently produce zero targets (an empty run).
        if efforts_override:
            levels = list(efforts_override)
        elif spec.efforts:
            levels = list(spec.efforts)
        else:
            levels = [None]
        for effort in levels:
            label = target_label(spec.id, effort)
            if label in seen:
                continue  # dedup: same (id, effort) requested twice
            seen.add(label)
            targets.append(
                RunTarget(
                    label=label,
                    model=spec.id,
                    effort=effort,  # type: ignore[arg-type]
                    price_override=spec.price_override,
                )
            )
    return targets


def build_run_config(
    *,
    models: list[str] | None = None,
    efforts: list[str] | None = None,
    k: int | None = None,
    temperature: float | None = None,
    timeout: float | None = None,
    max_spend_usd: float | None = None,
    max_tokens: int | None = None,
    dry_run: bool = False,
    prompt_style: str | None = None,
    models_yaml: str | Path | None = None,
) -> RunConfig:
    """Build a :class:`RunConfig` from CLI-supplied overrides with sane defaults.

    ``models`` defaults to every id in ``config/models.yaml`` when not supplied;
    ids passed explicitly still inherit any ``price_override``/``efforts`` from a
    matching yaml entry. ``efforts`` (e.g. ``["low", "high"]``) is a run-wide
    override that fans every selected model across those reasoning levels,
    ignoring per-entry ``efforts``. All other fields fall back to the
    module-level ``DEFAULT_*`` constants.
    """
    specs = load_model_specs(models_yaml)
    by_id = {spec.id: spec for spec in specs}

    if models:
        # Honor an explicit --models list, inheriting yaml metadata when present.
        selected = [by_id.get(mid, ModelSpec(id=mid)) for mid in models]
    else:
        selected = specs

    efforts_override = _validate_efforts(efforts, where="--efforts") if efforts else None
    targets = expand_targets(selected, efforts_override=efforts_override)

    style = prompt_style or DEFAULT_PROMPT_STYLE
    if style not in ("strict", "loose"):
        raise ValueError(f"prompt_style must be 'strict' or 'loose', got {style!r}")

    return RunConfig(
        models=[t.label for t in targets],
        k=k if k is not None else DEFAULT_K,
        temperature=temperature if temperature is not None else DEFAULT_TEMPERATURE,
        timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        max_spend_usd=(
            max_spend_usd if max_spend_usd is not None else DEFAULT_MAX_SPEND_USD
        ),
        dry_run=dry_run,
        prompt_style=style,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        targets=targets,
    )
