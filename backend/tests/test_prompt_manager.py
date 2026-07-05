"""Tests for the YAML-driven PromptManager.

Covers:
  - load() discovers all YAML files in prompts_dir
  - get() returns PromptConfig by name
  - get() returns None for unknown names
  - format_system() substitutes {placeholders}
  - format_system() leaves JSON braces untouched (no str.format)
  - missing placeholder is logged and left as-is
  - missing prompts_dir is tolerated (graceful)
  - output_model lazy resolution (valid path, bad path, None)
  - rubric loading (quality)
  - reload() re-reads from disk
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.prompt_manager import PromptConfig, PromptManager


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def real_manager() -> PromptManager:
    """PromptManager pointed at the real backend/app/prompts directory."""
    from app.services.prompt_manager import PROMPTS_DIR
    mgr = PromptManager(prompts_dir=PROMPTS_DIR)
    mgr.reload()
    return mgr


@pytest.fixture
def tmp_manager(tmp_path: Path) -> PromptManager:
    """Empty PromptManager pointed at a tmp dir (no YAML)."""
    return PromptManager(prompts_dir=tmp_path)


@pytest.fixture
def tmp_manager_with_one(tmp_path: Path) -> PromptManager:
    """PromptManager with a single YAML file containing one prompt + rubric."""
    yaml_content = """\
version: 1
rubrics:
  my_rubric:
    categories:
      foo:
        label: "Foo"
        criteria: "Be foo"
prompts:
  greeting:
    system: |-
      Hello {name}!
      Today is {day}.
      JSON: {"key": "value"}
    temperature: 0.5
    max_tokens: 100
    output_model: app.models.LLMResult
"""
    (tmp_path / "one.yaml").write_text(yaml_content, encoding="utf-8")
    mgr = PromptManager(prompts_dir=tmp_path)
    mgr.reload()
    return mgr


# ═══════════════════════════════════════════════════════════
# 1. Discovery & basic lookup
# ═══════════════════════════════════════════════════════════


class TestPromptManagerLoad:
    def test_loads_all_known_prompts(self, real_manager: PromptManager) -> None:
        names = set(real_manager.list_prompts())
        expected = {
            "summary", "sentiment", "conflict", "profanity", "topic",
            "quality", "validation", "resolution_sentiment", "error_classifier",
            "rag", "dict_analysis", "dict_suggest",
        }
        assert expected.issubset(names), (
            f"Missing prompts: {expected - names}"
        )

    def test_total_prompt_count(self, real_manager: PromptManager) -> None:
        """All 12 prompts are loaded."""
        assert len(real_manager.list_prompts()) >= 12

    def test_get_returns_prompt_config(self, real_manager: PromptManager) -> None:
        cfg = real_manager.get("sentiment")
        assert isinstance(cfg, PromptConfig)
        assert cfg.name == "sentiment"
        assert "аналитик колл-центра" in cfg.system

    def test_get_unknown_returns_none(self, real_manager: PromptManager) -> None:
        assert real_manager.get("does_not_exist") is None

    def test_lazy_load_on_first_get(self, tmp_path: Path) -> None:
        """get() triggers load() if not yet loaded."""
        (tmp_path / "x.yaml").write_text(
            "version: 1\nprompts:\n  p1:\n    system: hi\n",
            encoding="utf-8",
        )
        mgr = PromptManager(prompts_dir=tmp_path)
        assert mgr._loaded is False
        cfg = mgr.get("p1")
        assert cfg is not None
        assert cfg.system == "hi"
        assert mgr._loaded is True

    def test_missing_directory_tolerated(self, tmp_path: Path) -> None:
        """Missing prompts_dir logs warning but doesn't crash."""
        nonexistent = tmp_path / "nope"
        mgr = PromptManager(prompts_dir=nonexistent)
        mgr.reload()
        assert mgr.list_prompts() == []
        assert mgr.get("anything") is None


class TestPromptManagerReload:
    def test_reload_picks_up_new_file(self, tmp_path: Path) -> None:
        (tmp_path / "a.yaml").write_text(
            "version: 1\nprompts:\n  a:\n    system: A\n",
            encoding="utf-8",
        )
        mgr = PromptManager(prompts_dir=tmp_path)
        mgr.reload()
        assert "a" in mgr.list_prompts()

        # Add a new file
        (tmp_path / "b.yaml").write_text(
            "version: 1\nprompts:\n  b:\n    system: B\n",
            encoding="utf-8",
        )
        assert "b" not in mgr.list_prompts()  # cached
        mgr.reload()
        assert "b" in mgr.list_prompts()

    def test_reload_clears_stale_prompts(self, tmp_path: Path) -> None:
        f = tmp_path / "a.yaml"
        f.write_text(
            "version: 1\nprompts:\n  a:\n    system: A\n",
            encoding="utf-8",
        )
        mgr = PromptManager(prompts_dir=tmp_path)
        mgr.reload()
        assert "a" in mgr.list_prompts()

        f.unlink()
        mgr.reload()
        assert "a" not in mgr.list_prompts()


# ═══════════════════════════════════════════════════════════
# 2. PromptConfig attributes
# ═══════════════════════════════════════════════════════════


class TestPromptConfigAttributes:
    def test_defaults(self) -> None:
        cfg = PromptConfig("x", {})
        assert cfg.name == "x"
        assert cfg.system == ""
        assert cfg.temperature == 0.3
        assert cfg.max_tokens == 2000
        assert cfg.output_model_path is None
        assert cfg.output_model is None

    def test_explicit_values(self) -> None:
        cfg = PromptConfig("x", {
            "system": "hi",
            "temperature": 0.9,
            "max_tokens": 5000,
            "output_model": "app.models.LLMResult",
        })
        assert cfg.system == "hi"
        assert cfg.temperature == 0.9
        assert cfg.max_tokens == 5000
        assert cfg.output_model_path == "app.models.LLMResult"

    def test_rejects_non_dict(self) -> None:
        with pytest.raises(TypeError):
            PromptConfig("x", "not a dict")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════
# 3. format_system
# ═══════════════════════════════════════════════════════════


class TestFormatSystem:
    def test_substitutes_known_placeholder(self, tmp_manager_with_one: PromptManager) -> None:
        cfg = tmp_manager_with_one.get("greeting")
        assert cfg is not None
        result = cfg.format_system(name="Alice", day="Monday")
        assert "Hello Alice!" in result
        assert "Today is Monday." in result

    def test_leaves_json_braces_untouched(self, tmp_manager_with_one: PromptManager) -> None:
        """JSON braces in the prompt body are NOT interpreted as format specs."""
        cfg = tmp_manager_with_one.get("greeting")
        assert cfg is not None
        result = cfg.format_system(name="Alice", day="Monday")
        assert '{"key": "value"}' in result

    def test_missing_placeholder_left_as_is(self, tmp_manager_with_one: PromptManager) -> None:
        cfg = tmp_manager_with_one.get("greeting")
        assert cfg is not None
        # Don't pass `day` — the {day} token should remain in the output.
        result = cfg.format_system(name="Alice")
        assert "{day}" in result
        assert "Alice" in result

    def test_no_placeholders_returns_system_unchanged(self, tmp_manager_with_one: PromptManager) -> None:
        cfg = tmp_manager_with_one.get("greeting")
        assert cfg is not None
        # No kwargs at all — system returned verbatim.
        assert cfg.format_system() == cfg.system

    def test_quality_prompt_categories_substitution(self, real_manager: PromptManager) -> None:
        """The quality prompt's {categories} placeholder is replaced with
        the formatted category list and matches the inline constant."""
        from app.services.llm import _QUALITY_SYSTEM_PROMPT, _QUALITY_CATEGORY_LIST
        cfg = real_manager.get("quality")
        assert cfg is not None
        rendered = cfg.format_system(categories=_QUALITY_CATEGORY_LIST)
        assert rendered == _QUALITY_SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════
# 4. output_model resolution
# ═══════════════════════════════════════════════════════════


class TestOutputModelResolution:
    def test_resolves_valid_path(self, real_manager: PromptManager) -> None:
        from app.models import LLMResult, SentimentAnalysisResult
        assert real_manager.get("summary").output_model is LLMResult
        assert real_manager.get("sentiment").output_model is SentimentAnalysisResult

    def test_none_when_not_set(self, real_manager: PromptManager) -> None:
        assert real_manager.get("rag").output_model is None
        assert real_manager.get("dict_analysis").output_model is None

    def test_resolution_is_cached(self, tmp_path: Path) -> None:
        (tmp_path / "x.yaml").write_text(
            "version: 1\nprompts:\n  p:\n    system: s\n    output_model: app.models.LLMResult\n",
            encoding="utf-8",
        )
        mgr = PromptManager(prompts_dir=tmp_path)
        mgr.reload()
        cfg = mgr.get("p")
        # First access resolves
        m1 = cfg.output_model
        # Second access returns cached
        m2 = cfg.output_model
        assert m1 is m2

    def test_bad_path_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "x.yaml").write_text(
            "version: 1\nprompts:\n  p:\n    system: s\n    output_model: app.nonexistent.Foo\n",
            encoding="utf-8",
        )
        mgr = PromptManager(prompts_dir=tmp_path)
        mgr.reload()
        cfg = mgr.get("p")
        assert cfg.output_model is None

    def test_non_basemodel_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "x.yaml").write_text(
            "version: 1\nprompts:\n  p:\n    system: s\n    output_model: app.services.prompt_manager.PromptManager\n",
            encoding="utf-8",
        )
        mgr = PromptManager(prompts_dir=tmp_path)
        mgr.reload()
        cfg = mgr.get("p")
        assert cfg.output_model is None


# ═══════════════════════════════════════════════════════════
# 5. Rubric loading
# ═══════════════════════════════════════════════════════════


class TestRubricLoading:
    def test_quality_rubric_loaded(self, real_manager: PromptManager) -> None:
        rubric = real_manager.get_rubric("quality")
        assert isinstance(rubric, dict)
        assert "categories" in rubric
        assert "domains" in rubric

    def test_unknown_rubric_returns_empty(self, real_manager: PromptManager) -> None:
        assert real_manager.get_rubric("nonexistent") == {}

    def test_tmp_rubric_loaded(self, tmp_manager_with_one: PromptManager) -> None:
        rubric = tmp_manager_with_one.get_rubric("my_rubric")
        assert "categories" in rubric
        assert "foo" in rubric["categories"]
        assert rubric["categories"]["foo"]["label"] == "Foo"

    def test_list_rubrics(self, real_manager: PromptManager) -> None:
        assert "quality" in real_manager.list_rubrics()


# ═══════════════════════════════════════════════════════════
# 6. Bad YAML handling
# ═══════════════════════════════════════════════════════════


class TestBadYAMLHandling:
    def test_malformed_yaml_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "bad.yaml").write_text(
            "this: is: not: valid: yaml: [\n",
            encoding="utf-8",
        )
        (tmp_path / "good.yaml").write_text(
            "version: 1\nprompts:\n  good:\n    system: ok\n",
            encoding="utf-8",
        )
        mgr = PromptManager(prompts_dir=tmp_path)
        mgr.reload()
        # Bad file skipped, good file loaded
        assert "good" in mgr.list_prompts()

    def test_non_mapping_top_level_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "list.yaml").write_text(
            "- item1\n- item2\n",
            encoding="utf-8",
        )
        mgr = PromptManager(prompts_dir=tmp_path)
        mgr.reload()
        assert mgr.list_prompts() == []

    def test_bad_prompt_config_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "x.yaml").write_text(
            "version: 1\nprompts:\n  p:\n    system: ok\n  bad: \"just a string\"\n",
            encoding="utf-8",
        )
        mgr = PromptManager(prompts_dir=tmp_path)
        mgr.reload()
        # `p` loaded, `bad` (a string, not a dict) skipped
        assert "p" in mgr.list_prompts()
        assert "bad" not in mgr.list_prompts()


# ═══════════════════════════════════════════════════════════
# 7. Byte-identical parity with inline constants (backward compat)
# ═══════════════════════════════════════════════════════════


class TestInlineParity:
    """Every YAML prompt must be byte-identical to its inline counterpart.

    This guards the migration: the YAML is the new source of truth, but
    inline constants remain as fallback. They MUST produce identical
    strings so tests that assert exact prompt text continue to pass
    regardless of which source is active.
    """

    def test_summary_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.llm import _SYSTEM_PROMPT
        assert real_manager.get("summary").system == _SYSTEM_PROMPT

    def test_sentiment_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.llm import _SENTIMENT_SYSTEM_PROMPT
        assert real_manager.get("sentiment").system == _SENTIMENT_SYSTEM_PROMPT

    def test_conflict_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.llm import _CONFLICT_SYSTEM_PROMPT
        assert real_manager.get("conflict").system == _CONFLICT_SYSTEM_PROMPT

    def test_profanity_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.llm import _PROFANITY_SYSTEM_PROMPT
        assert real_manager.get("profanity").system == _PROFANITY_SYSTEM_PROMPT

    def test_topic_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.llm import _TOPIC_SYSTEM_PROMPT
        assert real_manager.get("topic").system == _TOPIC_SYSTEM_PROMPT

    def test_validation_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.llm import _VALIDATION_SYSTEM_PROMPT
        assert real_manager.get("validation").system == _VALIDATION_SYSTEM_PROMPT

    def test_resolution_sentiment_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.llm import _RESOLUTION_SENTIMENT_SYSTEM_PROMPT
        assert real_manager.get("resolution_sentiment").system == _RESOLUTION_SENTIMENT_SYSTEM_PROMPT

    def test_error_classifier_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.llm import _ERROR_CLASSIFIER_SYSTEM_PROMPT
        assert real_manager.get("error_classifier").system == _ERROR_CLASSIFIER_SYSTEM_PROMPT

    def test_rag_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.rag import _RAG_SYSTEM_PROMPT
        assert real_manager.get("rag").system == _RAG_SYSTEM_PROMPT

    def test_dict_analysis_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.dictionary_ai import ANALYSIS_SYSTEM_PROMPT
        assert real_manager.get("dict_analysis").system == ANALYSIS_SYSTEM_PROMPT

    def test_dict_suggest_matches_inline(self, real_manager: PromptManager) -> None:
        from app.services.dictionary_ai import SUGGEST_SYSTEM_PROMPT
        assert real_manager.get("dict_suggest").system == SUGGEST_SYSTEM_PROMPT
