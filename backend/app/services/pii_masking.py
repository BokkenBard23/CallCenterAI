"""PII Masking Service with Presidio for 152-FZ compliance.

Provides PII detection and anonymization for Russian/telecom text:
  - Presidio AnalyzerEngine with Russian NLP (spaCy ru_core_news_sm)
  - 7 custom NER recognizers for Russian/telecom formats
  - Strict blocking mode (Variant A): block if Presidio unavailable
  - Circuit breaker pattern (3 failures -> 60s open, consistent with embedding.py)
  - Semantic-neutral placeholders: <PERSON>, <PHONE>, <EMAIL>, etc.
  - Batch masking support
  - Observability (logging, latency metrics, get_stats())

INV-PII-1: PII masked BEFORE embedding/logging — never after.
INV-PII-3: Existing 1129+ tests must pass.
"""

from __future__ import annotations

import logging
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from app.models import (
    DialogueTurn,
    MaskedDialogueResult,
    ParsedDialog,
    PIIDetection,
    PIIEntityType,
    PIIMaskingConfig,
    PIIMaskingResult,
)

logger = logging.getLogger(__name__)

# Default configuration constants
_DEFAULT_LANGUAGE = "ru"
_DEFAULT_MIN_SCORE = 0.5
_DEFAULT_CIRCUIT_RESET_TIMEOUT = 60.0
_DEFAULT_FAILURE_THRESHOLD = 3

# Placeholder mapping: Presidio entity type -> semantic-neutral placeholder
_PRESIDIO_ENTITY_PLACEHOLDER_MAP: Dict[str, str] = {
    "PERSON": "<PERSON>",
    "PHONE_NUMBER": "<PHONE>",
    "EMAIL_ADDRESS": "<EMAIL>",
    "PASSPORT": "<PASSPORT>",
    "SNILS": "<SNILS>",
    "INN": "<INN>",
    "CREDIT_CARD": "<CARD>",
    "ADDRESS": "<ADDRESS>",
    "CONTRACT_NUMBER": "<CONTRACT>",
    "BILLING_ACCOUNT": "<BILLING>",
}

# PIIEntityType enum value -> Presidio entity type string
_ENTITY_TYPE_TO_PRESIDIO: Dict[str, str] = {
    PIIEntityType.person.value: "PERSON",
    PIIEntityType.phone_number.value: "PHONE_NUMBER",
    PIIEntityType.email_address.value: "EMAIL_ADDRESS",
    PIIEntityType.passport.value: "PASSPORT",
    PIIEntityType.snils.value: "SNILS",
    PIIEntityType.inn.value: "INN",
    PIIEntityType.credit_card.value: "CREDIT_CARD",
    PIIEntityType.address.value: "ADDRESS",
    PIIEntityType.contract_number.value: "CONTRACT_NUMBER",
    PIIEntityType.billing_account.value: "BILLING_ACCOUNT",
}


# ═══════════════════════════════════════════════════════════
# Checksum validation helpers
# ═══════════════════════════════════════════════════════════


def _snils_checksum(snils_digits: List[int]) -> bool:
    """Validate SNILS checksum (11 digits).

    Sum of digit[i] * (9 - i) for i = 0..8, compared with last 2 digits.
    If sum > 101, take sum % 101. If sum == 100, checksum = 00.
    """
    if len(snils_digits) != 11:
        return False
    total = sum(snils_digits[i] * (9 - i) for i in range(9))
    if total > 101:
        total = total % 101
    if total == 100:
        total = 0
    check = snils_digits[9] * 10 + snils_digits[10]
    return total == check


def _inn10_checksum(digits: List[int]) -> bool:
    """Validate 10-digit INN (legal entity) checksum."""
    if len(digits) != 10:
        return False
    weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    total = sum(digits[i] * weights[i] for i in range(9))
    check = total % 11
    if check > 9:
        check = check % 10
    return check == digits[9]


def _inn12_checksum(digits: List[int]) -> bool:
    """Validate 12-digit INN (individual) checksum."""
    if len(digits) != 12:
        return False
    weights1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    total1 = sum(digits[i] * weights1[i] for i in range(10))
    check1 = total1 % 11
    if check1 > 9:
        check1 = check1 % 10

    weights2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    total2 = sum(digits[i] * weights2[i] for i in range(11))
    check2 = total2 % 11
    if check2 > 9:
        check2 = check2 % 10

    return check1 == digits[10] and check2 == digits[11]


def _luhn_check(number_str: str) -> bool:
    """Validate credit card number using Luhn algorithm."""
    digits = [int(c) for c in number_str if c.isdigit()]
    if not digits:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ═══════════════════════════════════════════════════════════
# Custom Recognizers
# ═══════════════════════════════════════════════════════════


class RussianPhoneRecognizer(PatternRecognizer):
    """Recognizer for Russian phone numbers.

    Supports formats: +7(XXX)XXX-XX-XX, 8XXXXXXXXXX, 8(XXX)XXX-XX-XX,
    +7XXXXXXXXXX. Validates 11 digits after normalization.
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="ru_phone_plus7_parentheses",
                regex=r"\+7\s*\(?\d{3}\)?\s*\d{3}[-\s]?\d{2}[-\s]?\d{2}",
                score=0.5,
            ),
            Pattern(
                name="ru_phone_8_parentheses",
                regex=r"8\s*\(?\d{3}\)?\s*\d{3}[-\s]?\d{2}[-\s]?\d{2}",
                score=0.5,
            ),
            Pattern(
                name="ru_phone_8_continuous",
                regex=r"\b8\d{10}\b",
                score=0.4,
            ),
            Pattern(
                name="ru_phone_plus7_continuous",
                regex=r"\+7\d{10}",
                score=0.4,
            ),
        ]
        super().__init__(
            supported_entity="PHONE_NUMBER",
            patterns=patterns,
            context=["телефон", "звонить", "позвонить", "набрать", "номер", "мобильный", "сотовый"],
            supported_language="ru",
        )

    def validate_result(self, pattern_text: str) -> bool:
        """Validate: must have 11 digits after normalization."""
        digits = re.sub(r"\D", "", pattern_text)
        return len(digits) == 11


class PassportRecognizer(PatternRecognizer):
    """Recognizer for Russian passport series+number.

    Supports formats: XX XX XXXXXX, XX-XX-XXXXXX, XXXX XXXXXX.
    Validates series 01-99.
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="ru_passport_series_space",
                regex=r"\b(\d{2})\s+(\d{2})\s+(\d{6})\b",
                score=0.5,
            ),
            Pattern(
                name="ru_passport_series_dash",
                regex=r"\b(\d{2})-(\d{2})-(\d{6})\b",
                score=0.5,
            ),
            Pattern(
                name="ru_passport_four_six",
                regex=r"\b(\d{4})\s+(\d{6})\b",
                score=0.4,
            ),
        ]
        super().__init__(
            supported_entity="PASSPORT",
            patterns=patterns,
            context=["паспорт", "серия", "номер", "документ", "удостоверение"],
            supported_language="ru",
        )

    def validate_result(self, pattern_text: str) -> bool:
        """Validate: series must be 01-99."""
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) >= 2:
            series = int(digits[:2])
            return 1 <= series <= 99
        return False


class SNILSRecognizer(PatternRecognizer):
    """Recognizer for Russian SNILS (insurance number).

    Supports formats: XXX-XXX-XXX XX, XXXXXXXXXXX (11 digits), XXX-XXX-XXX-XX.
    Validates SNILS checksum algorithm.
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="ru_snils_dashed",
                regex=r"\b\d{3}-\d{3}-\d{3}\s+\d{2}\b",
                score=0.5,
            ),
            Pattern(
                name="ru_snils_continuous",
                regex=r"\b\d{11}\b",
                score=0.3,
            ),
            Pattern(
                name="ru_snils_all_dashed",
                regex=r"\b\d{3}-\d{3}-\d{3}-\d{2}\b",
                score=0.5,
            ),
        ]
        super().__init__(
            supported_entity="SNILS",
            patterns=patterns,
            context=["снилс", "страховой", "пенсионный", "страхование"],
            supported_language="ru",
        )

    def validate_result(self, pattern_text: str) -> bool:
        """Validate SNILS checksum."""
        digits = [int(c) for c in pattern_text if c.isdigit()]
        return _snils_checksum(digits)


class INNRecognizer(PatternRecognizer):
    """Recognizer for Russian INN (tax identification number).

    Supports 10-digit (legal entity) and 12-digit (individual) formats.
    Validates INN checksum for both lengths.
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="ru_inn_10digit",
                regex=r"\b\d{10}\b",
                score=0.3,
            ),
            Pattern(
                name="ru_inn_12digit",
                regex=r"\b\d{12}\b",
                score=0.3,
            ),
            Pattern(
                name="ru_inn_dashed",
                regex=r"\b\d{2,4}-\d{2,4}-\d{2,6}\b",
                score=0.3,
            ),
        ]
        super().__init__(
            supported_entity="INN",
            patterns=patterns,
            context=["инн", "налог", "налоговый", "индивидуальный"],
            supported_language="ru",
        )

    def validate_result(self, pattern_text: str) -> bool:
        """Validate INN checksum (10-digit or 12-digit)."""
        digits = [int(c) for c in pattern_text if c.isdigit()]
        if len(digits) == 10:
            return _inn10_checksum(digits)
        if len(digits) == 12:
            return _inn12_checksum(digits)
        return False


class RussianCreditCardRecognizer(PatternRecognizer):
    """Recognizer for credit/debit card numbers.

    Supports 16 digits (Visa/Mastercard/MIR) and 15 digits (Amex).
    Validates using Luhn algorithm.
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="credit_card_16_spaces",
                regex=r"\b\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\b",
                score=0.5,
            ),
            Pattern(
                name="credit_card_16_continuous",
                regex=r"\b\d{16}\b",
                score=0.4,
            ),
            Pattern(
                name="credit_card_15_amex",
                regex=r"\b\d{15}\b",
                score=0.3,
            ),
        ]
        super().__init__(
            supported_entity="CREDIT_CARD",
            patterns=patterns,
            context=["карта", "карточка", "кредитная", "дебетовая", "visa", "mastercard", "мир", "счёт", "cvv", "cvc"],
            supported_language="ru",
        )

    def validate_result(self, pattern_text: str) -> bool:
        """Validate card number using Luhn algorithm."""
        return _luhn_check(pattern_text)


class ContractNumberRecognizer(PatternRecognizer):
    """Recognizer for telecom contract numbers.

    Supports formats: Д-XXXXX/YYYY, Договор №XXXXX, К-XXXXX.
    Also detects arbitrary contract numbers near context words.
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="ru_contract_d_prefix",
                regex=r"\bД-\d+[/\\]\d+\b",
                score=0.7,
            ),
            Pattern(
                name="ru_contract_dogovor_number",
                regex=r"[Дд]оговор\s*№\s*\d+",
                score=0.7,
            ),
            Pattern(
                name="ru_contract_k_prefix",
                regex=r"\bК-\d+\b",
                score=0.6,
            ),
            Pattern(
                name="ru_contract_generic_number",
                regex=r"№\s*\d{3,}",
                score=0.3,
            ),
        ]
        super().__init__(
            supported_entity="CONTRACT_NUMBER",
            patterns=patterns,
            context=["договор", "контракт", "номер договора", "заключён", "подписан"],
            supported_language="ru",
        )


class BillingAccountRecognizer(PatternRecognizer):
    """Recognizer for telecom billing accounts.

    Supports formats: ЛС XXXXXXXXXX, Л/с XXXXXXXXXX,
    Лицевой счёт XXXXXXXXXX.
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="ru_billing_ls_prefix",
                regex=r"\bЛС\s+\d{4,}\b",
                score=0.7,
            ),
            Pattern(
                name="ru_billing_ls_slash",
                regex=r"\bЛ/с\s+\d{4,}\b",
                score=0.7,
            ),
            Pattern(
                name="ru_billing_licevoy",
                regex=r"[Лл]ицевой\s+счёт\s+\d{4,}",
                score=0.7,
            ),
        ]
        super().__init__(
            supported_entity="BILLING_ACCOUNT",
            patterns=patterns,
            context=["лицевой", "счёт", "л/с", "оплатить", "баланс", "начисление"],
            supported_language="ru",
        )


# ═══════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════


class _CircuitBreakerState(str, Enum):
    """Circuit breaker states, consistent with embedding.py pattern."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ═══════════════════════════════════════════════════════════
# PIIMaskingService
# ═══════════════════════════════════════════════════════════


class PIIMaskingService:
    """PII detection and masking service with Presidio.

    Variant A (strict blocking): if Presidio is unavailable, all masking
    operations return an error result — PII data is NEVER passed downstream
    unmasked. This satisfies 152-FZ compliance requirements.

    Circuit breaker pattern (consistent with embedding.py):
      - closed: normal operation
      - open: 3 consecutive failures → block for 60 seconds
      - half_open: after timeout, allow one probe request
      - success → closed, failure → open

    Features:
      - Presidio AnalyzerEngine with Russian NLP (spaCy ru_core_news_sm)
      - 7 custom NER recognizers for Russian/telecom formats
      - Semantic-neutral placeholders: <PERSON>, <PHONE>, <EMAIL>, etc.
      - Batch masking support
      - Observability (logging, latency metrics, get_stats())
    """

    def __init__(
        self,
        language: str = _DEFAULT_LANGUAGE,
        min_score_threshold: float = _DEFAULT_MIN_SCORE,
        circuit_reset_timeout: float = _DEFAULT_CIRCUIT_RESET_TIMEOUT,
        failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
    ) -> None:
        """Initialize PIIMaskingService.

        Args:
            language: Primary language for analysis (default: 'ru').
            min_score_threshold: Minimum confidence score for PII detection.
            circuit_reset_timeout: Seconds before circuit breaker auto-resets.
            failure_threshold: Number of failures before circuit opens.
        """
        self._language = language
        self._min_score_threshold = min_score_threshold
        self._circuit_reset_timeout = circuit_reset_timeout
        self._failure_threshold = failure_threshold

        # Circuit breaker state
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._circuit_state = _CircuitBreakerState.CLOSED

        # Availability flag
        self._available = False

        # Stats
        self._total_masked = 0
        self._entity_counts: Dict[str, int] = {}
        self._total_latency_ms = 0.0
        self._masking_count = 0

        # Presidio engines (initialized in _initialize)
        self._analyzer: Optional[AnalyzerEngine] = None
        self._anonymizer: Optional[AnonymizerEngine] = None

        # Initialize Presidio
        self._initialize()

    def _initialize(self) -> None:
        """Initialize Presidio AnalyzerEngine + AnonymizerEngine with custom recognizers.

        If initialization fails (spaCy model not found, Presidio error),
        sets _available = False and circuit breaker to OPEN.
        Variant A: processing will be BLOCKED until available.
        """
        try:
            # Create Russian NLP engine
            nlp_engine = NlpEngineProvider(
                nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "ru", "model_name": "ru_core_news_sm"}],
                }
            ).create_engine()

            # Create registry — do NOT use load_predefined_recognizers() because:
            # 1. It only registers English-language recognizers
            # 2. It conflicts with our custom CreditCardRecognizer name
            # Instead, manually add the recognizers we need with 'ru' language.
            from presidio_analyzer.predefined_recognizers import (
                EmailRecognizer,
                IpRecognizer,
                SpacyRecognizer,
                UrlRecognizer,
            )

            registry = RecognizerRegistry(supported_languages=["ru", "en"])

            # NLP-based recognizer for PERSON, LOCATION, ORGANIZATION (via spaCy)
            registry.add_recognizer(SpacyRecognizer(supported_language="ru"))
            registry.add_recognizer(SpacyRecognizer(supported_language="en"))

            # Predefined pattern recognizers we want for Russian text
            registry.add_recognizer(EmailRecognizer(supported_language="ru"))
            registry.add_recognizer(EmailRecognizer(supported_language="en"))
            registry.add_recognizer(UrlRecognizer(supported_language="ru"))
            registry.add_recognizer(UrlRecognizer(supported_language="en"))
            registry.add_recognizer(IpRecognizer(supported_language="ru"))
            registry.add_recognizer(IpRecognizer(supported_language="en"))

            # 7 custom recognizers for Russian/telecom formats
            custom_recognizers = [
                RussianPhoneRecognizer(),
                PassportRecognizer(),
                SNILSRecognizer(),
                INNRecognizer(),
                RussianCreditCardRecognizer(),
                ContractNumberRecognizer(),
                BillingAccountRecognizer(),
            ]
            for recognizer in custom_recognizers:
                registry.add_recognizer(recognizer)

            # Create analyzer — supported_languages must match registry
            self._analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine,
                registry=registry,
                supported_languages=["ru", "en"],
            )

            # Create anonymizer
            self._anonymizer = AnonymizerEngine()

            # Test availability with simple analyze call
            test_result = self._analyzer.analyze(
                text="Тестовый текст",
                language="ru",
            )
            # If we get here without error, Presidio is available
            self._available = True
            self._circuit_state = _CircuitBreakerState.CLOSED
            logger.info(
                "PIIMaskingService initialized successfully. "
                "Custom recognizers: %d. Language: %s.",
                len(custom_recognizers),
                self._language,
            )

        except Exception as exc:
            self._available = False
            self._circuit_state = _CircuitBreakerState.OPEN
            self._last_failure_time = time.time()
            logger.error(
                "PIIMaskingService initialization FAILED: %s. "
                "Circuit breaker OPEN. Variant A: all masking operations BLOCKED.",
                exc,
                exc_info=True,
            )

    # ── Circuit breaker ────────────────────────────────────────

    def _check_circuit(self) -> None:
        """Check circuit breaker state; auto-reset after timeout.

        Raises:
            RuntimeError: If circuit breaker is open (Variant A: block processing).
        """
        if self._circuit_state == _CircuitBreakerState.OPEN:
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self._circuit_reset_timeout:
                    # Transition to half-open — allow probe request
                    self._circuit_state = _CircuitBreakerState.HALF_OPEN
                    logger.info(
                        "PII circuit breaker → HALF_OPEN after %.0f sec. Probe allowed.",
                        elapsed,
                    )
                    return
            raise RuntimeError(
                "PII masking unavailable, processing blocked for compliance (152-FZ). "
                f"Circuit breaker OPEN. Auto-resets after {self._circuit_reset_timeout} sec."
            )

    def _record_failure(self) -> None:
        """Record a failure for circuit breaker tracking."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._failure_threshold:
            self._circuit_state = _CircuitBreakerState.OPEN
            self._available = False
            logger.error(
                "PII circuit breaker OPEN after %d failures. "
                "Auto-reset in %.0f sec. Variant A: processing BLOCKED.",
                self._failure_count,
                self._circuit_reset_timeout,
            )

    def _record_success(self) -> None:
        """Record a successful operation — reset failure count and close circuit."""
        self._failure_count = 0
        self._circuit_state = _CircuitBreakerState.CLOSED
        self._available = True

    # ── Core masking logic ─────────────────────────────────────

    def mask_text(
        self,
        text: str,
        config: Optional[PIIMaskingConfig] = None,
    ) -> PIIMaskingResult:
        """Mask PII entities in text using Presidio.

        Variant A: if Presidio unavailable or circuit breaker open,
        returns PIIMaskingResult with error — NEVER passes unmasked data.

        Args:
            text: Input text to mask.
            config: Optional masking configuration.

        Returns:
            PIIMaskingResult with masked_text or error.
        """
        start_time = time.time()

        # Handle None/empty input
        if text is None:
            return PIIMaskingResult(
                masked_text="",
                error="Input text is None",
            )
        if not text.strip():
            return PIIMaskingResult(
                masked_text=text,
            )

        # Circuit breaker check (Variant A)
        try:
            self._check_circuit()
        except RuntimeError as exc:
            return PIIMaskingResult(
                masked_text="",
                error=str(exc),
            )

        # Use defaults if no config
        if config is None:
            config = PIIMaskingConfig()

        try:
            # Determine which entities to analyze
            entities_to_analyze: Optional[List[str]] = None
            if config.entity_types:
                entities_to_analyze = [
                    _ENTITY_TYPE_TO_PRESIDIO[et.value]
                    for et in config.entity_types
                    if et.value in _ENTITY_TYPE_TO_PRESIDIO
                ]

            # Run Presidio analyzer
            analyzer_results = self._analyzer.analyze(
                text=text,
                language=self._language,
                entities=entities_to_analyze,
                score_threshold=config.min_score,
            )

            # Build detections from analyzer results
            detections: List[PIIDetection] = []
            for result in analyzer_results:
                presidio_entity = result.entity_type
                # Map back to our PIIEntityType
                pii_entity_type = None
                for our_type, presidio_type in _ENTITY_TYPE_TO_PRESIDIO.items():
                    if presidio_type == presidio_entity:
                        pii_entity_type = PIIEntityType(our_type)
                        break

                if pii_entity_type is None:
                    continue

                detections.append(
                    PIIDetection(
                        entity_type=pii_entity_type,
                        start=result.start,
                        end=result.end,
                        text=text[result.start : result.end],
                        score=result.score,
                        recognizer=result.recognition_metadata.get("recognizer_name", "unknown") if isinstance(result.recognition_metadata, dict) else "unknown",
                    )
                )

            # Build operator config for each entity type
            operators: Dict[str, OperatorConfig] = {}
            for presidio_type, placeholder in _PRESIDIO_ENTITY_PLACEHOLDER_MAP.items():
                operators[presidio_type] = OperatorConfig(
                    operator_name="replace",
                    params={"new_value": placeholder},
                )

            # Run Presidio anonymizer
            anonymizer_result = self._anonymizer.anonymize(
                text=text,
                analyzer_results=analyzer_results,
                operators=operators,
            )

            # Calculate entity counts
            entity_counts: Dict[str, int] = {}
            for detection in detections:
                key = detection.entity_type.value
                entity_counts[key] = entity_counts.get(key, 0) + 1

            # Calculate timing
            processing_time_ms = (time.time() - start_time) * 1000

            # Update stats
            self._total_masked += len(detections)
            for key, count in entity_counts.items():
                self._entity_counts[key] = self._entity_counts.get(key, 0) + count
            self._total_latency_ms += processing_time_ms
            self._masking_count += 1

            # Record success — reset circuit breaker
            self._record_success()

            return PIIMaskingResult(
                masked_text=anonymizer_result.text,
                detections=detections,
                entity_counts=entity_counts,
                processing_time_ms=round(processing_time_ms, 2),
                masked=len(detections) > 0,
            )

        except Exception as exc:
            self._record_failure()
            logger.error("PII masking failed: %s", exc, exc_info=True)
            return PIIMaskingResult(
                masked_text="",
                error=f"PII masking failed: {exc}",
            )

    def mask_texts(
        self,
        texts: List[str],
        config: Optional[PIIMaskingConfig] = None,
    ) -> List[PIIMaskingResult]:
        """Mask PII in a batch of texts.

        If circuit breaker is open, ALL texts return error result (Variant A).

        Args:
            texts: List of input texts to mask.
            config: Optional masking configuration.

        Returns:
            List of PIIMaskingResult, one per input text.
        """
        return [self.mask_text(text, config) for text in texts]

    def mask_dialogue(self, dialogue: ParsedDialog) -> MaskedDialogueResult:
        """Mask PII in all turns of a dialogue.

        Iterates over each DialogueTurn, calls mask_text() on turn.text,
        and builds a new ParsedDialog with masked text while preserving
        all other fields (speaker, timestamp, turn_index).

        Variant A (strict blocking): if any mask_text() returns an error,
        the entire dialogue masking is aborted and an error is returned.
        Unmasked dialogue is NEVER passed downstream (INV-PII-2).

        Args:
            dialogue: ParsedDialog with turns containing text to mask.

        Returns:
            MaskedDialogueResult with masked_dialogue (same structure, masked text)
            and error (set if masking failed — Variant A: BLOCK processing).
        """
        start_time = time.time()
        aggregate_entity_counts: Dict[str, int] = {}
        total_detections = 0
        masked_turns: List[DialogueTurn] = []

        for turn in dialogue.turns:
            result = self.mask_text(turn.text)

            # Variant A: stop on first failure
            if result.error:
                processing_time_ms = (time.time() - start_time) * 1000
                logger.error(
                    "PII masking failed on turn %d of '%s': %s",
                    turn.turn_index,
                    dialogue.filename,
                    result.error,
                )
                return MaskedDialogueResult(
                    masked_dialogue=None,
                    entity_counts=aggregate_entity_counts,
                    total_detections=total_detections,
                    processing_time_ms=round(processing_time_ms, 2),
                    error=f"Masking failed on turn {turn.turn_index}: {result.error}",
                )

            # Build masked turn — preserve all fields except text.
            # IMPORTANT: start_offset/end_offset MUST be carried over so that
            # downstream time-gap filters (_apply_time_gap_filter in
            # search.py) keep working when PII masking is enabled.
            # Regression 13.07→17.07: previously these fields were dropped,
            # which made _has_timestamps() return False and silently disabled
            # the SearchSpecifier (OnlyInGaps / ExcludeGaps) windows anchored
            # to dialogue bounds (StartEnd: First/Last) or parent matches
            # (Parent: Before/After). Symptom: when masking was ON (timestamps
            # lost → filter no-op → all matches passed → 11 found on 13.07);
            # when masking was OFF (timestamps preserved → filter active →
            # ExcludeGaps dropped the windowed matches → 0 found on 17.07).
            # Carrying offsets through masking makes the filter behave
            # identically in both modes.
            masked_turn = DialogueTurn(
                turn_index=turn.turn_index,
                speaker=turn.speaker,
                text=result.masked_text,
                timestamp=turn.timestamp,
                start_offset=turn.start_offset,
                end_offset=turn.end_offset,
            )
            masked_turns.append(masked_turn)

            # Aggregate entity counts
            for entity_type, count in result.entity_counts.items():
                aggregate_entity_counts[entity_type] = (
                    aggregate_entity_counts.get(entity_type, 0) + count
                )

            total_detections += len(result.detections)

        # Build masked ParsedDialog — preserve all fields, replace turns
        masked_dialogue = ParsedDialog(
            filename=dialogue.filename,
            turns=masked_turns,
            total_turns=dialogue.total_turns,
            client_turns=dialogue.client_turns,
            employee_turns=dialogue.employee_turns,
            parsed_at=dialogue.parsed_at,
        )

        processing_time_ms = (time.time() - start_time) * 1000

        logger.info(
            "PII dialogue masking complete: '%s', %d turns, %d detections, %.1f ms",
            dialogue.filename,
            len(masked_turns),
            total_detections,
            processing_time_ms,
        )

        return MaskedDialogueResult(
            masked_dialogue=masked_dialogue,
            entity_counts=aggregate_entity_counts,
            total_detections=total_detections,
            processing_time_ms=round(processing_time_ms, 2),
        )

    # ── Availability & Stats ─────────────────────────────────────

    def is_available(self) -> bool:
        """Check if PII masking service is available.

        Returns:
            True if Presidio is available and circuit breaker is not open.
        """
        if self._circuit_state == _CircuitBreakerState.OPEN:
            # Check if auto-reset timeout has passed
            try:
                self._check_circuit()
            except RuntimeError:
                return False
        return self._available

    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics.

        Returns:
            Dictionary with total_masked, entity_counts, avg_latency_ms,
            circuit_breaker_state, available.
        """
        avg_latency = (
            self._total_latency_ms / self._masking_count
            if self._masking_count > 0
            else 0.0
        )
        return {
            "total_masked": self._total_masked,
            "entity_counts": dict(self._entity_counts),
            "avg_latency_ms": round(avg_latency, 2),
            "circuit_breaker_state": self._circuit_state.value,
            "available": self._available,
            "failure_count": self._failure_count,
            "masking_count": self._masking_count,
        }
