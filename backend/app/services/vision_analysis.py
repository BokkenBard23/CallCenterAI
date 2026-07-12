"""Vision analysis service — multimodal LLM screenshot analysis with fallback chain.

Provides a unified async interface for sending PNG/JPEG screenshots to multimodal
LLM providers available via Beeline AI OpenAI-compatible endpoint.

Fallback chain (based on vision benchmark 2026-07-12, see
docs/specs/screenshots/vision-benchmark/VISION_BENCHMARK_RESULTS.md):
    gpt-5.4 → qwen-medium-dense → qwen-medium

Benchmark results (3 tests, 7 models):
    gpt-5.4             — 100% accuracy, 5.5s avg (BEST quality)
    qwen-medium-dense   —  67% accuracy, 3.6s avg (FASTEST)
    qwen-medium         —  67% accuracy, 4.8s avg (guaranteed Beeline infra)
    claude-sonnet-4-5   —  67% accuracy, 6.4s avg
    claude-opus-4-6     —  67% accuracy, 6.7s avg
    gemini-2.5-pro      —  67% accuracy, 12.8s avg (slowest)
    qwen-medium-preview —  67% accuracy, 4.7s avg

gpt-5.4 is primary — it was the ONLY model that correctly identified that
tab text was NOT truncated (all others gave false positives on a 19px button
background clip while text was fully visible).

qwen-medium-dense and qwen-medium are fallbacks: direct Beeline infrastructure,
no Guardrails Exo errors, guaranteed recovery.

Usage:
    from app.services.vision_analysis import analyze_screenshot

    result = await analyze_screenshot(
        image_path="docs/specs/screenshots/mining-desktop-1440.png",
        prompt="Опиши визуальные проблемы на скриншоте.",
    )
    # → {"text": "...", "model": "gpt-5.4"}

CLI (for ui-tester / orchestrator without Python httpx in Node.js):
    python -m app.services.vision_analysis --image <path> --prompt <text>
    python -m app.services.vision_analysis --image <path> --prompt-file <path>

OpenAI-compatible chat completions API at api.ai.beeline.ru.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import ssl
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT = 120.0  # vision models are slower than text
_MAX_RETRIES = 1  # per-model retry before falling through

# Fallback chain based on vision benchmark (2026-07-12):
# 1. gpt-5.4 (best accuracy 100%, may hit Guardrails Exo)
# 2. qwen-medium-dense (fastest 3.6s, 67% accuracy, no Guardrails — direct Beeline infra)
# 3. qwen-medium (guaranteed available, no Guardrails — direct Beeline infra)
#
# Benchmark details: docs/specs/screenshots/vision-benchmark/VISION_BENCHMARK_RESULTS.md
_VISION_MODELS: List[str] = [
    "gpt-5.4",
    "qwen-medium-dense",
    "qwen-medium",
]

# Models that go through Guardrails and MAY intermittently fail with Exo error.
# Qwen models are direct Beeline infrastructure and do NOT go through Guardrails.
_GUARDRAILS_MODELS = {"gpt-5.4", "gemini-2.5-pro", "claude-sonnet-4-5", "claude-opus-4-6"}


def _build_ssl_context() -> ssl.SSLContext:
    """Build SSL context with verification disabled (corporate TLS compat).

    Same approach as BeelineAIProvider in app.services.llm.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _encode_image(image_path: str | Path) -> Tuple[str, str]:
    """Read image file and return (base64_data, mime_type).

    Args:
        image_path: Path to PNG or JPEG file.

    Returns:
        Tuple of (base64_string, "image/png" | "image/jpeg").

    Raises:
        FileNotFoundError: If image_path does not exist.
        ValueError: If file extension is not .png/.jpg/.jpeg.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    ext = path.suffix.lower()
    if ext == ".png":
        mime = "image/png"
    elif ext in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    else:
        raise ValueError(f"Unsupported image format: {ext} (use .png or .jpg)")

    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return b64, mime


def _build_payload(
    model: str,
    prompt: str,
    image_b64: str,
    mime: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    """Build OpenAI-compatible chat completions payload with image_url content."""
    messages: List[Dict[str, Any]] = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_b64}"},
            },
        ],
    })

    return {
        "model": model,
        "stream": False,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def _is_guardrails_error(response_text: str, status_code: int) -> bool:
    """Detect Guardrails Exo error patterns in response.

    Guardrails Exo errors may appear as:
    - HTTP 200 with error text in body
    - HTTP 4xx/5xx with "guardrails" or "exo" in error message
    - Empty response with guardrails mention
    """
    combined = f"{response_text} {status_code}".lower()
    return any(
        pattern in combined
        for pattern in ("guardrails", "exo", "content_filter", "content policy")
    )


async def _try_model(
    client: httpx.AsyncClient,
    model: str,
    payload: Dict[str, Any],
    api_key: str,
) -> Tuple[bool, str, Optional[str]]:
    """Try a single model. Returns (success, content, error).

    Args:
        client: httpx async client (already configured with SSL).
        model: Model ID (replaced in payload).
        payload: Request payload (model field will be overwritten).
        api_key: Beeline AI API key.

    Returns:
        (success, content, error_message)
    """
    # Override model in payload
    payload = {**payload, "model": model}
    url = "https://api.ai.beeline.ru/api/v3/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.post(url, json=payload, headers=headers)

            # Guardrails Exo may return non-200 with error in body
            if response.status_code != 200:
                error_text = response.text[:500]
                if _is_guardrails_error(error_text, response.status_code):
                    logger.warning(
                        "Vision model %s: Guardrails Exo error (HTTP %d): %s",
                        model,
                        response.status_code,
                        error_text[:200],
                    )
                    return False, "", f"guardrails_exo: {error_text[:200]}"
                # Non-guardrails HTTP error — retry once, then fail through
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "Vision model %s HTTP %d (attempt %d), retrying: %s",
                        model,
                        response.status_code,
                        attempt + 1,
                        error_text[:200],
                    )
                    await asyncio.sleep(2 ** attempt)
                    continue
                return False, "", f"http_{response.status_code}: {error_text[:200]}"

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                logger.warning(
                    "Vision model %s: empty choices in response", model
                )
                return False, "", "empty_choices"

            content = choices[0].get("message", {}).get("content", "")
            if not content or not content.strip():
                # Empty content may indicate Guardrails filter
                if model in _GUARDRAILS_MODELS:
                    logger.warning(
                        "Vision model %s: empty content (possible Guardrails filter)",
                        model,
                    )
                    return False, "", "empty_content_guardrails"
                logger.warning("Vision model %s: empty content", model)
                return False, "", "empty_content"

            # Check if content itself is a guardrails error message
            if _is_guardrails_error(content, 200):
                logger.warning(
                    "Vision model %s: Guardrails error in content body: %s",
                    model,
                    content[:200],
                )
                return False, "", f"guardrails_in_content: {content[:200]}"

            logger.info(
                "Vision model %s: SUCCESS (%d chars response)", model, len(content)
            )
            return True, content, None

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "Vision model %s network error (attempt %d): %s — retrying",
                    model,
                    attempt + 1,
                    exc,
                )
                await asyncio.sleep(2 ** attempt)
                continue
            return False, "", f"network_error: {exc}"
        except Exception as exc:
            logger.error("Vision model %s unexpected error: %s", model, exc)
            return False, "", f"unexpected: {exc}"

    return False, "", "max_retries_exceeded"


async def analyze_screenshot(
    image_path: str | Path,
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    models: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Analyze a screenshot using multimodal LLM with fallback chain.

    Tries models in order: gpt-5.4 → qwen-medium-dense → qwen-medium.

    gpt-5.4 is primary (100% accuracy in vision benchmark).
    Qwen models are guaranteed fallback (direct Beeline infra, no Guardrails Exo).

    Args:
        image_path: Path to PNG or JPEG screenshot.
        prompt: Text prompt describing what to analyze.
        system_prompt: Optional system prompt for role/instructions.
        temperature: Sampling temperature (default 0.3 for consistent analysis).
        max_tokens: Max tokens in response (default 4096).
        models: Override default fallback chain (for testing).

    Returns:
        Dict with keys:
            - text: str — LLM response text
            - model: str — model that succeeded
            - attempts: List[Dict] — per-model attempt log
            - success: bool

    Raises:
        FileNotFoundError: If image_path does not exist.
        ValueError: If image format is unsupported.
        ConnectionError: If ALL models fail (including Qwen fallback).
    """
    api_key = settings.beeline_api_key
    if not api_key:
        raise ConnectionError("BEELINE_API_KEY not configured")

    image_b64, mime = _encode_image(image_path)
    payload = _build_payload(
        model="",  # Will be overridden per-model
        prompt=prompt,
        image_b64=image_b64,
        mime=mime,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    chain = models or _VISION_MODELS
    attempts: List[Dict[str, Any]] = []
    ssl_ctx = _build_ssl_context()

    async with httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT, verify=ssl_ctx
    ) as client:
        for model in chain:
            logger.info("Vision analysis: trying model %s", model)
            success, content, error = await _try_model(client, model, payload, api_key)

            attempt_record = {
                "model": model,
                "success": success,
                "error": error,
                "is_guardrails": error.startswith("guardrails")
                    if error else False,
                "content_length": len(content) if success else 0,
            }
            attempts.append(attempt_record)

            if success:
                return {
                    "text": content,
                    "model": model,
                    "attempts": attempts,
                    "success": True,
                }

            logger.warning(
                "Vision model %s failed: %s — trying next in chain",
                model,
                error,
            )

    # All models failed
    all_errors = [a["error"] for a in attempts]
    raise ConnectionError(
        f"All vision models failed. Attempts: {json.dumps(attempts, indent=2, ensure_ascii=False)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point (for use from Node.js/OpenCode agents)
# ─────────────────────────────────────────────────────────────────────────────


def _cli() -> int:
    """CLI entry point for vision analysis.

    Usage:
        python -m app.services.vision_analysis --image <path> --prompt <text>
        python -m app.services.vision_analysis --image <path> --prompt-file <path>
        python -m app.services.vision_analysis --image <path> --prompt <text> --output <path>

    Exit codes:
        0 — success
        1 — all models failed
        2 — invalid arguments
        3 — file not found / unsupported format
    """
    parser = argparse.ArgumentParser(
        description="Analyze a screenshot using multimodal LLM with fallback chain"
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Path to PNG or JPEG screenshot",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="Analysis prompt (inline)",
    )
    parser.add_argument(
        "--prompt-file",
        default=None,
        help="Path to file containing analysis prompt (UTF-8)",
    )
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="Optional system prompt",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write analysis result (UTF-8). If omitted, prints to stdout.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full JSON result (attempts, model, text) instead of just text",
    )
    args = parser.parse_args()

    # Resolve prompt
    if args.prompt:
        prompt = args.prompt
    elif args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    else:
        print("Error: either --prompt or --prompt-file is required", file=sys.stderr)
        return 2

    # Run async analysis
    try:
        result = asyncio.run(
            analyze_screenshot(
                image_path=args.image,
                prompt=prompt,
                system_prompt=args.system_prompt,
            )
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    except ConnectionError as e:
        print(f"Error: All models failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1

    # Output result
    if args.json:
        output = json.dumps(result, indent=2, ensure_ascii=False)
    else:
        output = result["text"]

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(
            f"Analysis saved to {args.output} "
            f"(model: {result['model']}, attempts: {len(result['attempts'])})",
            file=sys.stderr,
        )
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
