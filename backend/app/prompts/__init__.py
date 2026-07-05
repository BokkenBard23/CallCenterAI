"""YAML-driven prompt definitions for the LLM layer.

Prompts in this directory are loaded at runtime by
:mod:`app.services.prompt_manager`. They are editable without code
redeploy (edit YAML + restart). Inline constants in
:mod:`app.services.llm` and :mod:`app.services.dictionary_ai` are kept
as backward-compat fallback.
"""
