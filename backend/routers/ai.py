"""AI-assistant endpoints (Phase 6, task QQQ).

Thin wrapper around :mod:`backend.ai_assistant` exposing a single endpoint
that turns a natural-language prompt into a DSL flow JSON the automation
interpreter can run. The frontend ``AutomationForm`` "AI Build" button
calls this and pipes the result into the flow editor.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import ai_assistant
from ..dependencies import get_current_user
from ..models import AiBuildRequest, AiBuildResponse

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/build-automation", response_model=AiBuildResponse)
async def build_automation(
    body: AiBuildRequest,
    _: dict = Depends(get_current_user),
) -> AiBuildResponse:
    if not body.prompt or len(body.prompt.strip()) < 5:
        raise HTTPException(400, "Prompt is too short")
    if len(body.prompt) > 4000:
        raise HTTPException(400, "Prompt is too long (max 4000 chars)")
    try:
        dsl = await ai_assistant.generate_flow(body.prompt)
    except ValueError as e:
        raise HTTPException(502, str(e))
    return AiBuildResponse(dsl=dsl, configured=ai_assistant.is_configured())
