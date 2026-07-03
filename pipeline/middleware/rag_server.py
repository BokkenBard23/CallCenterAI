"""MCP server wrapper for Beeline AI RAG API.

Connects to https://api.ai.beeline.ru/api/v2 and exposes RAG tools
via MCP (Model Context Protocol) SSE transport.

Environment variables:
    RAG_API_KEY       — Beeline AI API key (default from backend/.env)
    RAG_BASE_URL      — Base URL (default: https://api.ai.beeline.ru/api/v2)
    RAG_KB_CODE       — Knowledge base deployment code
    RAG_LLM_DEPLOYMENT — LLM model name (default: gemma-3-27b-it)
    RAG_TOP_K         — Number of documents to return (default: 10)
    RAG_SSL_VERIFY    — SSL verify: "false"/"0" to skip, path to CA bundle, or auto-detect
    RAG_HOST          — Server host (default: 127.0.0.1)
    RAG_PORT          — Server port (default: 8765)
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://api.ai.beeline.ru/api/v2"
DEFAULT_KB_CODE = "permanent-api-crq411646-assistant_platform-ml-platform-prod-knowlege_base_helpdesk"
DEFAULT_LLM_DEPLOYMENT = "glm-5.1"
DEFAULT_TOP_K = 10

# Try to load API key from backend/.env if not set
_DEFAULT_API_KEY = ""
_env_path = Path(__file__).resolve().parents[2] / "backend" / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("BEELINE_API_KEY=") or line.startswith("BEELINE_AI_API_KEY="):
            _DEFAULT_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

# ── MCP Server Factory ─────────────────────────────────────────────────────


def _create_mcp(host: str, port: int):
    """Create and return the FastMCP server instance."""
    server = FastMCP(
        "beeline-rag-knowledge",
        host=host,
        port=port,
    )

    @server.tool()
    async def rag_query(
        text: str,
        top_k: int = DEFAULT_TOP_K,
        search_deployment: str | None = None,
        llm_deployment: str | None = None,
    ) -> str:
        """Query the Beeline AI Knowledge Base (RAG).

        Args:
            text: Query text to search the knowledge base.
            top_k: Number of documents to return (default from env or 10).
            search_deployment: Knowledge base code (overrides env var).
            llm_deployment: LLM model name (overrides env var).

        Returns:
            JSON string with the RAG inference result including answer, sources, and usage.
        """
        kb_code = search_deployment or _get_kb_code()
        llm_model = llm_deployment or _get_llm_deployment()
        top = top_k or _get_top_k()

        payload = {
            "text": text,
            "topK": top,
            "searchDeployment": kb_code,
            "llmDeployment": llm_model,
        }

        result = await _post("/Rag/inference", payload)
        return _format_rag_response(result)

    @server.tool()
    async def rag_query_stream(
        text: str,
        top_k: int = DEFAULT_TOP_K,
        search_deployment: str | None = None,
        llm_deployment: str | None = None,
    ) -> str:
        """Query the Beeline AI Knowledge Base with streaming response.

        Args:
            text: Query text to search the knowledge base.
            top_k: Number of documents to return (default from env or 10).
            search_deployment: Knowledge base code (overrides env var).
            llm_deployment: LLM model name (overrides env var).

        Returns:
            JSON string with the full streaming response (all chunks collected).
        """
        kb_code = search_deployment or _get_kb_code()
        llm_model = llm_deployment or _get_llm_deployment()
        top = top_k or _get_top_k()

        url = f"{_get_base_url()}/Rag/inference/stream"
        payload = {
            "text": text,
            "topK": top,
            "searchDeployment": kb_code,
            "llmDeployment": llm_model,
        }

        async with httpx.AsyncClient(timeout=120.0, verify=_get_ssl_verify()) as client:
            async with client.stream("POST", url, headers=_headers(), json=payload) as resp:
                resp.raise_for_status()
                chunks = []
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunks.append(json.loads(data))
                        except json.JSONDecodeError:
                            chunks.append({"raw": data})
                return json.dumps({"chunks": chunks, "count": len(chunks)}, ensure_ascii=False, indent=2)

    @server.tool()
    async def list_files(search_deployment: str | None = None) -> str:
        """List files metadata in the Knowledge Base.

        Args:
            search_deployment: Knowledge base code (overrides env var).

        Returns:
            JSON string with file metadata list.
        """
        kb_code = search_deployment or _get_kb_code()
        result = await _get(f"/Search/deployments/{kb_code}/files/metadata")
        return json.dumps(result, ensure_ascii=False, indent=2)

    @server.tool()
    async def add_file(
        file_path: str,
        chunk_size: int | None = None,
        search_deployment: str | None = None,
    ) -> str:
        """Add a file to the Knowledge Base.

        Args:
            file_path: Local path to the file to upload.
            chunk_size: Chunk size for document splitting (optional).
            search_deployment: Knowledge base code (overrides env var).

        Returns:
            JSON string with upload result.
        """
        kb_code = search_deployment or _get_kb_code()
        abs_path = Path(file_path).resolve()

        if not abs_path.exists():
            return json.dumps({"error": f"File not found: {abs_path}"}, ensure_ascii=False, indent=2)

        url = f"{_get_base_url()}/Search/deployments/{kb_code}/files"
        data: dict[str, Any] = {}
        if chunk_size is not None:
            data["ChunkSize"] = chunk_size

        with open(abs_path, "rb") as f:
            files = {"Files": (abs_path.name, f, "application/octet-stream")}
            async with httpx.AsyncClient(timeout=300.0, verify=_get_ssl_verify()) as client:
                resp = await client.post(
                    url,
                    headers=_headers(),
                    data=data,
                    files=files,
                )
                resp.raise_for_status()
                return json.dumps(resp.json(), ensure_ascii=False, indent=2)

    @server.tool()
    async def delete_file(
        file_code: str,
        search_deployment: str | None = None,
    ) -> str:
        """Delete a file from the Knowledge Base.

        Args:
            file_code: File code returned from list_files.
            search_deployment: Knowledge base code (overrides env var).

        Returns:
            JSON string with deletion result.
        """
        kb_code = search_deployment or _get_kb_code()
        result = await _delete(f"/Search/deployments/{kb_code}/files/{file_code}")
        return json.dumps(result, ensure_ascii=False, indent=2)

    @server.tool()
    async def get_kb_info(search_deployment: str | None = None) -> str:
        """Get knowledge base deployment info and token limits.

        Args:
            search_deployment: Knowledge base code (overrides env var).

        Returns:
            JSON string with KB info.
        """
        kb_code = search_deployment or _get_kb_code()
        try:
            url = f"{_get_base_url()}/me/token_limits?model={_get_llm_deployment()}"
            result = await _get(url)
            return json.dumps({"token_limits": result, "kb_code": kb_code}, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"kb_code": kb_code, "error": str(e)}, ensure_ascii=False, indent=2)

    return server

# ── HTTP Client ─────────────────────────────────────────────────────────────


def _get_api_key() -> str:
    return os.environ.get("RAG_API_KEY") or _DEFAULT_API_KEY


def _get_base_url() -> str:
    return os.environ.get("RAG_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _get_kb_code() -> str:
    return os.environ.get("RAG_KB_CODE", DEFAULT_KB_CODE)


def _get_llm_deployment() -> str:
    return os.environ.get("RAG_LLM_DEPLOYMENT", DEFAULT_LLM_DEPLOYMENT)


def _get_top_k() -> int:
    return int(os.environ.get("RAG_TOP_K", str(DEFAULT_TOP_K)))


def _get_ssl_verify() -> bool | str:
    """Determine SSL verification setting.

    Priority:
        1. RAG_SSL_VERIFY env var: "false"/"0" → False, path → str (CA bundle), else True
        2. Auto-detect: if the corporate CA bundle exists at .opencode-pipeline/certs/ca-bundle.pem,
           use it; otherwise default to False (corporate network without public CA chain).

    For internal Beeline API servers the certificate is signed by Corporate CA
    which is not in the standard trust store, so we default to verify=False unless
    an explicit CA path is provided.
    """
    env = os.environ.get("RAG_SSL_VERIFY", "").strip().lower()

    if env in ("false", "0", "no"):
        return False
    if env in ("true", "1", "yes"):
        # Try auto-detected corporate CA
        ca_path = Path(__file__).resolve().parents[2] / ".opencode-pipeline" / "certs" / "ca-bundle.pem"
        if ca_path.exists():
            return str(ca_path)
        return True
    if env:  # Treat as a file path
        p = Path(env)
        if p.exists():
            return str(p)
        print(f"[rag_server] WARNING: RAG_SSL_VERIFY path not found: {env}", file=sys.stderr)
        return True

    # Auto-detect: check for corporate CA bundle
    ca_path = Path(__file__).resolve().parents[2] / ".opencode-pipeline" / "certs" / "ca-bundle.pem"
    if ca_path.exists():
        return str(ca_path)

    # Default for internal Beeline API: skip SSL verify
    return False


def _format_rag_response(result: dict[str, Any]) -> str:
    """Extract and format the answer from the OpenAI-compatible RAG response."""
    # OpenAI ChatCompletion format: choices[0].message.content
    answer = ""
    choices = result.get("choices", [])
    if choices and isinstance(choices, list):
        message = choices[0].get("message", {})
        answer = message.get("content", "")

    usage = result.get("usage", {})
    model = result.get("model", "")

    formatted = {
        "answer": answer,
        "model": model,
        "usage": usage,
    }
    return json.dumps(formatted, ensure_ascii=False, indent=2)


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    key = _get_api_key()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST JSON to the RAG API and return parsed JSON."""
    url = f"{_get_base_url()}{path}"
    async with httpx.AsyncClient(timeout=120.0, verify=_get_ssl_verify()) as client:
        resp = await client.post(url, headers=_headers(), json=payload)
        resp.raise_for_status()
        return resp.json()


async def _get(path: str) -> dict[str, Any]:
    """GET from the RAG API and return parsed JSON."""
    url = f"{_get_base_url()}{path}"
    async with httpx.AsyncClient(timeout=30.0, verify=_get_ssl_verify()) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def _delete(path: str) -> dict[str, Any]:
    """DELETE from the RAG API and return parsed JSON."""
    url = f"{_get_base_url()}{path}"
    async with httpx.AsyncClient(timeout=30.0, verify=_get_ssl_verify()) as client:
        resp = await client.delete(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Beeline AI RAG MCP Server")
    parser.add_argument("--host", default=None, help="Server host (overrides RAG_HOST)")
    parser.add_argument("--port", type=int, default=None, help="Server port (overrides RAG_PORT)")
    args = parser.parse_args()

    host = args.host or os.environ.get("RAG_HOST", "127.0.0.1")
    port = args.port or int(os.environ.get("RAG_PORT", "8765"))

    print(f"Starting Beeline AI RAG MCP server on {host}:{port} ...", file=sys.stderr)
    print(f"  API URL: {_get_base_url()}", file=sys.stderr)
    print(f"  KB Code: {_get_kb_code()}", file=sys.stderr)
    print(f"  LLM Model: {_get_llm_deployment()}", file=sys.stderr)
    print(f"  SSL Verify: {_get_ssl_verify()}", file=sys.stderr)
    print(f"  API Key: {'*' * 8}{_get_api_key()[-4:] if _get_api_key() else '(not set)'}", file=sys.stderr)
    print("", file=sys.stderr)

    server = _create_mcp(host, port)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
