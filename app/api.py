"""REST API: lets other software (hospital systems, the coder workstation) request code suggestions
and record approved coding decisions."""
import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Response

from pydantic import BaseModel, Field

from app import audit, claims
from app.engine import MODEL_VERSION, CodingEngine

log = logging.getLogger(__name__)
engine = None


@asynccontextmanager
async def lifespan(app):
    global engine
    engine = CodingEngine()          # connect to Ollama once, when the API starts
    yield


app = FastAPI(
    title="Clinical Coding Copilot API",
    description="Suggests ICD-10-CM codes for clinical text, checked against official coding rules, "
                "and records every approved coding decision. Demo system: do not send real patient data.",
    version="1.1.0",
    lifespan=lifespan,
)


CASE_ID_PATTERN = r"^[A-Za-z0-9_-]+$"


class CaseIn(BaseModel):
    text: str = Field(..., min_length=20, max_length=20000, description="Clinical note in English")
    case_id: str | None = Field(None, pattern=CASE_ID_PATTERN, max_length=64, description="Your own reference for this case (optional)")


class Diagnosis(BaseModel):
    code: str
    type: str = Field(..., pattern="^(Principal|Secondary)$")


class ReviewIn(BaseModel):
    case_id: str = Field(..., pattern=CASE_ID_PATTERN, max_length=64)
    coder: str = Field(..., min_length=1)
    model_version: str
    note_text: str
    ai_suggested: list[str]
    diagnoses: list[Diagnosis] = Field(..., min_length=1)
    removed_by_coder: list[str]
    added_by_coder: list[str]
    ai_latency_seconds: float | None = None
    review_seconds: float | None = None


@app.get("/health")
def health():
    """Is the service up, and which model is it using?"""
    return {"status": "ok", "model": engine.model, "model_version": MODEL_VERSION}


@app.post("/suggest")
def suggest(case: CaseIn):
    """Return suggested codes: accepted, flagged for review, and rejected (with reasons)."""
    try:
        result = engine.suggest(case.text)
    except Exception:
        log.exception("Coding engine error")
        raise HTTPException(status_code=503, detail="Coding engine unavailable")
    return {"case_id": case.case_id or str(uuid.uuid4()), **result}


@app.post("/reviews")
def create_review(review: ReviewIn):
    """Store an approved coding decision in the audit trail."""
    if sum(d.type == "Principal" for d in review.diagnoses) != 1:
        raise HTTPException(status_code=422, detail="Exactly one Principal diagnosis is required")
    return {"review_id": audit.save_review(review.model_dump())}


@app.get("/reviews")
def get_reviews(limit: int = Query(50, ge=1, le=10000)):
    """Most recent approved reviews (newest first)."""
    return audit.list_reviews(limit)



@app.get("/reviews/{review_id}/claim.xml")
def export_claim(review_id: int):
    """Scrub an approved review and export it as a claim-style XML file (demo format)."""
    review = audit.get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found")
    problems = claims.scrub(review)
    if problems:
        raise HTTPException(status_code=422, detail={"message": "Claim blocked by scrubber", "problems": problems})
    return Response(content=claims.build_claim_xml(review), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="claim_{review["case_id"]}_{review_id}.xml"'})