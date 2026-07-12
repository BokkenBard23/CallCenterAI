#!/usr/bin/env bash
# Vision analysis CLI wrapper — sends a screenshot to multimodal LLM with fallback chain.
#
# Usage:
#   scripts/vision-analyze.sh <image_path> "<prompt>" [output_path]
#   scripts/vision-analyze.sh <image_path> --prompt-file <prompt_path> [output_path]
#
# Fallback chain (per user requirement):
#   gemini-2.5-pro → gpt-5.4 → claude-sonnet-4-5 → qwen-medium-preview (3.6) → qwen-medium (3.5)
#
# Exit codes:
#   0 — success
#   1 — all models failed
#   2 — invalid arguments
#   3 — file not found / unsupported format
#
# Backend must be configured with BEELINE_API_KEY in backend/.env

set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: $0 <image_path> <prompt_or_flag> [output_path]" >&2
  echo "  $0 screenshot.png \"Describe visual issues\"" >&2
  echo "  $0 screenshot.png --prompt-file prompt.txt output.md" >&2
  exit 2
fi

IMAGE="$1"
shift

# Detect --prompt-file vs inline prompt
if [ "$1" = "--prompt-file" ]; then
  shift
  PROMPT_FILE="$1"
  shift
else
  PROMPT="$1"
  shift
  PROMPT_FILE=""
fi

OUTPUT="${1:-}"

# Resolve project root (script is in scripts/, backend is sibling)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT/backend"

export PYTHONPATH="."
export PYTHONIOENCODING="utf-8"

if [ -n "$PROMPT_FILE" ]; then
  if [ -n "$OUTPUT" ]; then
    python -m app.services.vision_analysis \
      --image "$IMAGE" \
      --prompt-file "$PROMPT_FILE" \
      --output "$OUTPUT"
  else
    python -m app.services.vision_analysis \
      --image "$IMAGE" \
      --prompt-file "$PROMPT_FILE"
  fi
else
  if [ -n "$OUTPUT" ]; then
    python -m app.services.vision_analysis \
      --image "$IMAGE" \
      --prompt "$PROMPT" \
      --output "$OUTPUT"
  else
    python -m app.services.vision_analysis \
      --image "$IMAGE" \
      --prompt "$PROMPT"
  fi
fi
