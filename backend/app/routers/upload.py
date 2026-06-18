"""Upload router — RTF and XML dictionary upload endpoints.

TODO (coder stage):
  - Implement RTF file upload → parse with smartlogger.rtf_parser
  - Implement XML dictionary upload → parse with services.xml_parser
  - Add file size validation (config.max_upload_bytes)
  - Store parsed data in session store
"""

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models import UploadRtfResponse, UploadDictionaryResponse
from app.utils.session import session_store

router = APIRouter()


@router.post("/rtf", response_model=UploadRtfResponse, summary="Upload RTF dialog file")
async def upload_rtf(file: UploadFile = File(...)) -> UploadRtfResponse:
    """Upload and parse an RTF dialog transcript.

    Accepts .rtf files containing call center dialogues.
    Returns parsed dialogue with speaker-labeled turns.
    """
    # TODO: Validate file extension (.rtf)
    # TODO: Validate file size (settings.max_upload_bytes)
    # TODO: Read file content and parse with services.rtf_parser
    # TODO: Store parsed dialog in session_store
    raise HTTPException(status_code=501, detail="RTF upload not yet implemented")


@router.post("/dictionary", response_model=UploadDictionaryResponse, summary="Upload XML dictionary")
async def upload_dictionary(file: UploadFile = File(...)) -> UploadDictionaryResponse:
    """Upload and parse an XML phrase dictionary.

    Accepts .xml files with quarterly phrase groups (Q1, Q2, Q3).
    Returns parsed dictionary with conditions per quarter.
    """
    # TODO: Validate file extension (.xml)
    # TODO: Validate file size (settings.max_upload_bytes)
    # TODO: Read file content and parse with services.xml_parser
    # TODO: Store parsed dictionary in session_store
    raise HTTPException(status_code=501, detail="Dictionary upload not yet implemented")
