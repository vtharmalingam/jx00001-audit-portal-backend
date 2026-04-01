"""Knowledge base search and gap analysis (LLM)."""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate

from app.rest.deps import llm_client, semantic_engine
from app.rest.v1.knowledge_schemas import GapAnalysisBody, SemanticSearchBody, SynthesisGapOutput

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/semantic-search", summary="Semantic search over the configured collection")
async def semantic_search(body: SemanticSearchBody):
    raw = semantic_engine.semantic_summary(body.context, body.count)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"data": raw}
    return {"data": raw}


def _summaries_to_text(summaries: List[Dict[str, Any]]) -> str:
    return "\n\n".join(
        f"""Document: {s.get('doc_id', 'N/A')}
          Type: {s.get('chunk_type', 'N/A')}
          Score: {round(s.get('score', 0), 3)}
          Section: {' > '.join(s.get('section_path', []))}

          Text:
          {s.get('text', '')}
          """.strip()
        for s in summaries
        if s.get("text")
    )


@router.post("/gap-analysis", summary="Gap analysis vs retrieved KB context (LLM)")
async def gap_analysis(body: GapAnalysisBody):
    if not all([body.index_name, body.question, body.user_answer]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION", "message": "index_name, question, user_answer required"},
        )

    supportwiz_response = semantic_engine.semantic_summary(body.question, 10)
    payload: Dict[str, Any] = {}
    if isinstance(supportwiz_response, dict):
        payload.update(supportwiz_response)
    elif isinstance(supportwiz_response, list):
        payload["data"] = supportwiz_response
    else:
        payload["data"] = supportwiz_response

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "NO_RESULTS", "message": "Semantic search returned no results for gap analysis"},
        )

    summaries_text = _summaries_to_text(results)

    prompt = ChatPromptTemplate.from_template(
        """
    You are an enterprise knowledge synthesis and gap analysis assistant.

    Your task MUST be executed in TWO STRICTLY SEPARATED STEPS.

    ────────────────────────────────────────────────────────
    STEP 1 — AUTHORITATIVE SYNTHESIS
    ────────────────────────────────────────────────────────
    - Derive the correct and complete answer to the USER QUESTION.
    - Use ONLY the RETRIEVED CONTEXT provided.
    - Do NOT use prior knowledge, assumptions, or external information.
    - If the retrieved context is insufficient, explicitly state that limitation.
    - This synthesized answer will be treated as the reference truth.

    ────────────────────────────────────────────────────────
    STEP 2 — GAP ANALYSIS AGAINST USER ANSWER
    ────────────────────────────────────────────────────────
    - Compare the USER ANSWER strictly against the synthesized answer from STEP 1.
    - Identify ONLY what is missing, incomplete, unclear, or incorrect.
    - Do NOT restate the synthesized answer verbatim.
    - Do NOT evaluate tone, writing style, or intent.
    - Focus purely on factual, conceptual, or procedural gaps.
    - Frame gaps as constructive guidance for improvement.

    ────────────────────────────────────────────────────────
    GLOBAL RULES
    ────────────────────────────────────────────────────────
    - No speculation.
    - No hallucination.
    - No content outside the retrieved context.
    - Use precise, neutral, professional language.
    - Maintain clear traceability between synthesis and identified gaps.
    - Return ONLY valid JSON matching the provided schema.

    {format_instructions}

    ────────────────────────────────────────────────────────
    USER QUESTION:
    {question}

    QUESTION INTENT:
    {question_intent}

    ────────────────────────────────────────────────────────
    USER ANSWER:
    {user_answer}

    ────────────────────────────────────────────────────────
    RETRIEVED CONTEXT (Knowledge Base):
    {content}
    ────────────────────────────────────────────────────────
    """
    )

    parser = JsonOutputParser(pydantic_object=SynthesisGapOutput)
    chain = (
        prompt.partial(format_instructions=parser.get_format_instructions())
        | llm_client
        | parser
    )

    try:
        ai_summary = chain.invoke(
            {
                "content": summaries_text,
                "question": body.question,
                "user_answer": body.user_answer,
                "question_intent": (
                    "Evaluate implementation gaps between the user's answer and the "
                    "authoritative synthesized answer derived from the knowledge base"
                ),
            }
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "GAP_ANALYSIS_FAILED", "message": str(e)},
        ) from e

    return {
        "customer_id": body.customer_id,
        "question_id": body.question_id,
        "index_name": body.index_name,
        "data": ai_summary,
    }
