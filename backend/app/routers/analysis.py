"""Analysis router — Dialog analysis and results endpoints.

TODO (coder stage):
  - Implement /analyze endpoint: run dictionary matching via services.search
  - Implement /analyze-with-llm endpoint: matching + LLM enrichment
  - Implement /results/{session_id} endpoint: retrieve stored analysis
  - Validate session_id exists before analysis
"""

from fastapi import APIRouter, HTTPException

from app.models import AnalysisResponse
from app.utils.session import session_store

router = APIRouter()


@router.post("/analyze", response_model=AnalysisResponse, summary="Run dictionary analysis")
async def analyze_dialog(session_id: str) -> AnalysisResponse:
    """Run phrase-matching analysis on a previously uploaded dialogue.

    Uses the smartlogger sliding-window engine against the loaded dictionary.
    """
    # TODO: Validate session exists
    # TODO: Retrieve parsed dialog and dictionary from session_store
    # TODO: Run services.search.match_dialog()
    # TODO: Build AnalysisResult with matches
    # TODO: Store result in session_store
    raise HTTPException(status_code=501, detail="Analysis not yet implemented")


@router.post(
    "/analyze-with-llm",
    response_model=AnalysisResponse,
    summary="Run analysis with LLM enrichment",
)
async def analyze_with_llm(
    session_id: str,
    provider: str = "ollama",
) -> AnalysisResponse:
    """Run dictionary matching + LLM-based analysis.

    Combines smartlogger phrase matching with LLM topic/sentiment analysis.
    """
    # TODO: Run dictionary analysis first
    # TODO: Call services.llm.analyze_dialogue()
    # TODO: Merge results into AnalysisResponse
    raise HTTPException(status_code=501, detail="LLM analysis not yet implemented")


@router.get(
    "/results/{session_id}",
    response_model=AnalysisResponse,
    summary="Get analysis results",
)
async def get_results(session_id: str) -> AnalysisResponse:
    """Retrieve stored analysis results for a session."""
    # TODO: Look up session_id in session_store
    # TODO: Return stored AnalysisResponse or 404
    raise HTTPException(status_code=501, detail="Results retrieval not yet implemented")
