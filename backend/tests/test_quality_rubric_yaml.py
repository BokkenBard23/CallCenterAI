"""Tests for the enriched quality rubric in quality.yaml.

Covers:
  - rubric loads with `categories` and `domains` sections
  - 12 base categories (enum-backed) are present with label + criteria
  - 4 call-center-specific enrichments are present:
      script_adherence, client_identification, pii_handling, first_call_resolution
  - each category has the required keys (label, criteria)
  - in_enum flag distinguishes enum-backed vs advisory categories
  - per-domain extras exist for telecom, banking, insurance, healthcare
  - quality prompt references the {categories} placeholder
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from app.models import QualityCategory, QUALITY_CATEGORY_LABELS
from app.services.prompt_manager import prompt_manager


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def rubric() -> Dict[str, Any]:
    prompt_manager.reload()
    r = prompt_manager.get_rubric("quality")
    assert r, "quality rubric not loaded"
    return r


# ═══════════════════════════════════════════════════════════
# 1. Rubric structure
# ═══════════════════════════════════════════════════════════


class TestRubricStructure:
    def test_rubric_is_dict(self, rubric: Dict[str, Any]) -> None:
        assert isinstance(rubric, dict)

    def test_has_categories_key(self, rubric: Dict[str, Any]) -> None:
        assert "categories" in rubric
        assert isinstance(rubric["categories"], dict)

    def test_has_domains_key(self, rubric: Dict[str, Any]) -> None:
        assert "domains" in rubric
        assert isinstance(rubric["domains"], dict)

    def test_at_least_16_categories(self, rubric: Dict[str, Any]) -> None:
        """12 enum-backed + 4 enrichments."""
        assert len(rubric["categories"]) >= 16


# ═══════════════════════════════════════════════════════════
# 2. 12 base categories mirror the QualityCategory enum
# ═══════════════════════════════════════════════════════════


class TestBaseCategories:
    @pytest.mark.parametrize("cat", [c.value for c in QualityCategory])
    def test_enum_category_present(self, rubric: Dict[str, Any], cat: str) -> None:
        assert cat in rubric["categories"], (
            f"Enum category {cat!r} missing from rubric"
        )

    @pytest.mark.parametrize("cat", [c.value for c in QualityCategory])
    def test_enum_category_label_matches_models(
        self, rubric: Dict[str, Any], cat: str,
    ) -> None:
        """Labels in YAML must match QUALITY_CATEGORY_LABELS in models.py."""
        assert rubric["categories"][cat]["label"] == QUALITY_CATEGORY_LABELS[cat]

    @pytest.mark.parametrize("cat", [c.value for c in QualityCategory])
    def test_enum_category_marked_in_enum(
        self, rubric: Dict[str, Any], cat: str,
    ) -> None:
        assert rubric["categories"][cat].get("in_enum") is True

    def test_exactly_12_in_enum_categories(self, rubric: Dict[str, Any]) -> None:
        in_enum = [
            name for name, cfg in rubric["categories"].items()
            if cfg.get("in_enum") is True
        ]
        assert len(in_enum) == 12
        assert set(in_enum) == {c.value for c in QualityCategory}


# ═══════════════════════════════════════════════════════════
# 3. Call-center-specific enrichments
# ═══════════════════════════════════════════════════════════


ENRICHMENT_CATEGORIES = [
    "script_adherence",
    "client_identification",
    "pii_handling",
    "first_call_resolution",
]


class TestEnrichmentCategories:
    @pytest.mark.parametrize("cat", ENRICHMENT_CATEGORIES)
    def test_enrichment_present(self, rubric: Dict[str, Any], cat: str) -> None:
        assert cat in rubric["categories"], (
            f"Enrichment category {cat!r} missing"
        )

    @pytest.mark.parametrize("cat", ENRICHMENT_CATEGORIES)
    def test_enrichment_has_label(self, rubric: Dict[str, Any], cat: str) -> None:
        label = rubric["categories"][cat].get("label")
        assert isinstance(label, str) and label.strip()

    @pytest.mark.parametrize("cat", ENRICHMENT_CATEGORIES)
    def test_enrichment_has_criteria(self, rubric: Dict[str, Any], cat: str) -> None:
        criteria = rubric["categories"][cat].get("criteria")
        assert isinstance(criteria, str) and criteria.strip()

    @pytest.mark.parametrize("cat", ENRICHMENT_CATEGORIES)
    def test_enrichment_not_in_enum(self, rubric: Dict[str, Any], cat: str) -> None:
        """Enrichment categories are advisory — not backed by QualityCategory enum."""
        assert rubric["categories"][cat].get("in_enum") is False
        assert cat not in [c.value for c in QualityCategory]

    def test_script_adherence_label(self, rubric: Dict[str, Any]) -> None:
        assert rubric["categories"]["script_adherence"]["label"] == "Соблюдение скрипта"

    def test_client_identification_label(self, rubric: Dict[str, Any]) -> None:
        assert rubric["categories"]["client_identification"]["label"] == "Идентификация клиента"

    def test_pii_handling_label(self, rubric: Dict[str, Any]) -> None:
        assert rubric["categories"]["pii_handling"]["label"] == "Корректность работы с ПДн"

    def test_first_call_resolution_label(self, rubric: Dict[str, Any]) -> None:
        assert rubric["categories"]["first_call_resolution"]["label"] == "Решение при первом обращении (FCR)"

    def test_pii_handling_mentions_152_fz(self, rubric: Dict[str, Any]) -> None:
        """PII handling criteria should reference 152-ФЗ."""
        criteria = rubric["categories"]["pii_handling"]["criteria"]
        assert "152" in criteria or "ПДн" in criteria

    def test_client_identification_mentions_152_fz(self, rubric: Dict[str, Any]) -> None:
        criteria = rubric["categories"]["client_identification"]["criteria"]
        assert "152" in criteria


# ═══════════════════════════════════════════════════════════
# 4. Per-domain extras
# ═══════════════════════════════════════════════════════════


class TestDomainExtras:
    @pytest.mark.parametrize("domain", ["telecom", "banking", "insurance", "healthcare"])
    def test_domain_present(self, rubric: Dict[str, Any], domain: str) -> None:
        assert domain in rubric["domains"], f"Domain {domain!r} missing"

    @pytest.mark.parametrize("domain", ["telecom", "banking", "insurance", "healthcare"])
    def test_domain_has_extra_categories(
        self, rubric: Dict[str, Any], domain: str,
    ) -> None:
        extras = rubric["domains"][domain].get("extra_categories", {})
        assert isinstance(extras, dict)
        assert len(extras) >= 1, f"Domain {domain} has no extra categories"

    def test_telecom_has_tariff_explanation(self, rubric: Dict[str, Any]) -> None:
        assert "tariff_explanation" in rubric["domains"]["telecom"]["extra_categories"]

    def test_telecom_has_retention(self, rubric: Dict[str, Any]) -> None:
        assert "retention" in rubric["domains"]["telecom"]["extra_categories"]

    def test_banking_has_transaction_security(self, rubric: Dict[str, Any]) -> None:
        assert "transaction_security" in rubric["domains"]["banking"]["extra_categories"]

    def test_all_domain_extras_have_label_and_criteria(self, rubric: Dict[str, Any]) -> None:
        for domain, dcfg in rubric["domains"].items():
            extras = dcfg.get("extra_categories", {})
            for cat_name, cat_cfg in extras.items():
                assert "label" in cat_cfg, (
                    f"{domain}.{cat_name} missing 'label'"
                )
                assert "criteria" in cat_cfg, (
                    f"{domain}.{cat_name} missing 'criteria'"
                )
                assert isinstance(cat_cfg["label"], str) and cat_cfg["label"].strip()
                assert isinstance(cat_cfg["criteria"], str) and cat_cfg["criteria"].strip()
                # Domain extras are advisory
                assert cat_cfg.get("in_enum") is False


# ═══════════════════════════════════════════════════════════
# 5. All categories have required keys
# ═══════════════════════════════════════════════════════════


class TestAllCategoriesWellFormed:
    def test_every_base_category_has_label_and_criteria(
        self, rubric: Dict[str, Any],
    ) -> None:
        for name, cfg in rubric["categories"].items():
            assert "label" in cfg, f"{name} missing 'label'"
            assert "criteria" in cfg, f"{name} missing 'criteria'"
            assert isinstance(cfg["label"], str) and cfg["label"].strip()
            assert isinstance(cfg["criteria"], str) and cfg["criteria"].strip()
            assert "in_enum" in cfg, f"{name} missing 'in_enum' flag"

    def test_every_category_has_distinct_label(self, rubric: Dict[str, Any]) -> None:
        labels = [cfg["label"] for cfg in rubric["categories"].values()]
        assert len(labels) == len(set(labels)), "Duplicate labels found"


# ═══════════════════════════════════════════════════════════
# 6. Quality prompt references the rubric
# ═══════════════════════════════════════════════════════════


class TestQualityPromptIntegration:
    def test_quality_prompt_exists(self) -> None:
        cfg = prompt_manager.get("quality")
        assert cfg is not None

    def test_quality_prompt_has_categories_placeholder(self) -> None:
        cfg = prompt_manager.get("quality")
        assert cfg is not None
        assert "{categories}" in cfg.system

    def test_quality_prompt_mentions_12_categories(self) -> None:
        cfg = prompt_manager.get("quality")
        assert cfg is not None
        assert "12 категорий" in cfg.system

    def test_quality_prompt_output_model(self) -> None:
        from app.models import QualityScoreResult
        cfg = prompt_manager.get("quality")
        assert cfg is not None
        assert cfg.output_model is QualityScoreResult

    def test_quality_prompt_renders_with_categories(self) -> None:
        """When {categories} is substituted, the result matches the inline
        _QUALITY_SYSTEM_PROMPT — proves YAML is the source of truth."""
        from app.services.llm import _QUALITY_SYSTEM_PROMPT, _QUALITY_CATEGORY_LIST
        cfg = prompt_manager.get("quality")
        assert cfg is not None
        rendered = cfg.format_system(categories=_QUALITY_CATEGORY_LIST)
        assert rendered == _QUALITY_SYSTEM_PROMPT
        # Sanity: rendered text mentions every enum category
        for cat in QualityCategory:
            assert cat.value in rendered


# ═══════════════════════════════════════════════════════════
# 7. Rubric is JSON-serialisable (for future API exposure)
# ═══════════════════════════════════════════════════════════


class TestRubricSerializable:
    def test_rubric_json_serializable(self, rubric: Dict[str, Any]) -> None:
        import json
        s = json.dumps(rubric, ensure_ascii=False)
        assert "categories" in s
        assert "script_adherence" in s
        restored = json.loads(s)
        assert restored["categories"]["script_adherence"]["label"] == "Соблюдение скрипта"
