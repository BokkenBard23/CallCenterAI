"""YAML-driven prompt manager.

Loads prompts from ``backend/app/prompts/*.yaml`` at startup and provides
prompt lookup by name with placeholder substitution. Prompts are editable
without code redeploy (edit YAML + restart).

Ported from Callytics ``text/prompt.py`` pattern, adapted to our
multi-file layout (one YAML per concern) and lazy ``output_model``
resolution by dotted path.

Design notes
------------
* **Backward compatibility**: when the YAML file or a specific prompt
  is missing, :meth:`PromptManager.get` returns ``None`` and callers
  fall back to their inline constants (see ``app.services.llm``).
* **Idempotent**: :meth:`load` may be called multiple times.
* **Rubrics**: alongside ``prompts``, YAML files may declare a
  ``rubrics`` top-level key (e.g. ``quality`` rubric config) which is
  retrieved via :meth:`get_rubric`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class PromptConfig:
    """Single prompt configuration loaded from YAML.

    Attributes:
        name: Prompt key within the ``prompts:`` mapping.
        system: System prompt text (may contain ``{placeholders}``).
        temperature: Sampling temperature hint (callers may ignore).
        max_tokens: Max-tokens hint (callers may ignore).
        output_model_path: Dotted path to a Pydantic model class for
            structured parsing, e.g. ``app.models.LLMResult``.
            ``None`` means free-text output.
    """

    def __init__(self, name: str, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise TypeError(
                f"PromptConfig data must be a dict, got {type(data).__name__}"
            )
        self.name: str = name
        self.system: str = str(data.get("system", ""))
        self.temperature: float = float(data.get("temperature", 0.3))
        self.max_tokens: int = int(data.get("max_tokens", 2000))
        output_model_raw = data.get("output_model")
        self.output_model_path: Optional[str] = (
            output_model_raw if output_model_raw else None
        )
        self._output_model: Optional[Type[BaseModel]] = None
        self._output_model_resolved: bool = False

    @property
    def output_model(self) -> Optional[Type[BaseModel]]:
        """Lazily resolve ``output_model_path`` to a Pydantic class.

        Resolution failures (bad import path) log a warning and return
        ``None`` rather than raising — callers must tolerate ``None``.
        """
        if self._output_model_resolved:
            return self._output_model
        self._output_model_resolved = True
        if not self.output_model_path:
            return None
        module_path, _, class_name = self.output_model_path.rpartition(".")
        if not module_path or not class_name:
            logger.warning(
                "PromptConfig(%s): invalid output_model path %r",
                self.name, self.output_model_path,
            )
            return None
        try:
            module = __import__(module_path, fromlist=[class_name])
            resolved = getattr(module, class_name)
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "PromptConfig(%s): could not resolve output_model %s: %s",
                self.name, self.output_model_path, exc,
            )
            return None
        if not isinstance(resolved, type) or not issubclass(resolved, BaseModel):
            logger.warning(
                "PromptConfig(%s): output_model %s is not a Pydantic BaseModel",
                self.name, self.output_model_path,
            )
            return None
        self._output_model = resolved
        return self._output_model

    def format_system(self, **kwargs: Any) -> str:
        """Substitute ``{placeholder}`` tokens in the system prompt.

        Uses plain :py:meth:`str.replace` for each key (NOT
        :py:meth:`str.format`), so JSON braces in the prompt body are
        left untouched. This is critical for prompts that embed JSON
        examples (e.g. the quality prompt contains ``{"category": ...}``
        which would otherwise be misread as a format spec).

        Missing keys are logged at DEBUG and left unsubstituted.
        """
        if not kwargs:
            return self.system
        result = self.system
        for key, value in kwargs.items():
            token = "{" + key + "}"
            if token in result:
                result = result.replace(token, str(value))
            else:
                logger.debug(
                    "PromptConfig(%s): placeholder %s not found in template",
                    self.name, token,
                )
        return result


class PromptManager:
    """Loads and caches prompts from YAML files.

    The manager is lazy: the first call to :meth:`get` / :meth:`get_rubric`
    triggers :meth:`load`. Call :meth:`load` explicitly to force a reload
    (e.g. in tests that swap the YAML files).
    """

    def __init__(self, prompts_dir: Optional[Path] = None) -> None:
        self.prompts_dir: Path = prompts_dir or PROMPTS_DIR
        self._prompts: Dict[str, PromptConfig] = {}
        self._rubrics: Dict[str, Dict[str, Any]] = {}
        self._loaded: bool = False

    # ── Loading ────────────────────────────────────────────────

    def load(self) -> None:
        """Load all YAML files from ``prompts_dir``. Idempotent.

        A missing directory is logged but not fatal (callers fall back
        to inline prompts). Per-file parse errors are logged and the
        rest of the files are still loaded.
        """
        self._prompts.clear()
        self._rubrics.clear()
        self._loaded = True

        if not self.prompts_dir.exists():
            logger.warning(
                "Prompts directory not found: %s — using inline fallback",
                self.prompts_dir,
            )
            return

        for yaml_file in sorted(self.prompts_dir.glob("*.yaml")):
            try:
                with open(yaml_file, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
            except (OSError, yaml.YAMLError) as exc:
                logger.error(
                    "Failed to load prompts from %s: %s", yaml_file, exc,
                )
                continue
            if not isinstance(data, dict):
                logger.warning(
                    "Skipping %s: top-level YAML is not a mapping", yaml_file.name,
                )
                continue

            prompts_data = data.get("prompts") or {}
            if isinstance(prompts_data, dict):
                for name, prompt_data in prompts_data.items():
                    try:
                        self._prompts[name] = PromptConfig(name, prompt_data)
                    except (TypeError, ValueError) as exc:
                        logger.error(
                            "Bad prompt config %r in %s: %s",
                            name, yaml_file.name, exc,
                        )

            rubrics_data = data.get("rubrics") or {}
            if isinstance(rubrics_data, dict):
                for key, rubric_data in rubrics_data.items():
                    if isinstance(rubric_data, dict):
                        self._rubrics[key] = rubric_data

            logger.info(
                "Loaded %d prompts from %s",
                len(prompts_data) if isinstance(prompts_data, dict) else 0,
                yaml_file.name,
            )

        logger.info("Total prompts loaded: %d", len(self._prompts))

    def reload(self) -> None:
        """Alias for :meth:`load` — re-reads YAML from disk."""
        self._loaded = False
        self.load()

    # ── Lookup ────────────────────────────────────────────────

    def get(self, name: str) -> Optional[PromptConfig]:
        """Get prompt by name. Auto-loads on first access."""
        if not self._loaded:
            self.load()
        return self._prompts.get(name)

    def get_rubric(self, name: str) -> Dict[str, Any]:
        """Get rubric config by name (e.g. ``"quality"``)."""
        if not self._loaded:
            self.load()
        return self._rubrics.get(name, {})

    def list_prompts(self) -> List[str]:
        """Return sorted list of all known prompt names."""
        if not self._loaded:
            self.load()
        return sorted(self._prompts.keys())

    def list_rubrics(self) -> List[str]:
        """Return sorted list of all known rubric names."""
        if not self._loaded:
            self.load()
        return sorted(self._rubrics.keys())


# Module-level singleton. Callers may construct their own PromptManager
# (e.g. with a custom dir for tests) but most production code shares this.
prompt_manager = PromptManager()
