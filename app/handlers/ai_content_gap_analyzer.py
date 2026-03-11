from typing import Any, Dict, List, Optional

from app.config import get_config
from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.procs.embeddings import EmbeddingModel

# from chat_server.services.support_data_client import SupportDataClient
from langchain_core.output_parsers import (JsonOutputParser,
                                           PydanticOutputParser)
from langchain_core.prompts.chat import ChatPromptTemplate
from pydantic import BaseModel, Field, confloat, conlist

from app.procs.anchor_match.question_registry import \
    QuestionRegistry

from app.procs.semantic_search.q_search_engine import SemanticSearchEngine

# TODO: Move this to main and pass to the routes
from app.llms.ollama_client import OllamaClient


# S3 Services:
from app.etl.s3.services.answer_service import AnswerService
from app.etl.s3.services.auditor_service import AuditorService
from app.etl.s3.services.report_service import ReportService
from app.etl.s3.services.operational_service import OperationalService

from app.etl.s3.services.s3_client import S3Client

cfg = get_config()
data_dir = cfg.ai_assessment.data_dir


# --------------------------------------------------------------------------------
# TODO: Move these to main or part of connection object (manager)
# --------------------------------------------------------------------------------
llm_client = OllamaClient().llm
s3_client = S3Client(bucket=cfg.ai_assessment.s3.bucket)


# -----------------------------------------------------------------------------
emb_cfg = cfg.ai_assessment.embedding
engine = SemanticSearchEngine(emb_cfg.collection_name)


# ---------------------------------------------------
#   REQUEST 1:
# 
#   TODO: audit_id -> 0 (hard-coded)
# 
# ---------------------------------------------------
@route("AI-ASSESSMENT-REQ", "SAVE-ANSWER")
async def save_answer(ws,  
                      client_id, 
                      request, 
                      manager):
         
  
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData
    
    if not reqData:     
        await emitter.error("🚩 Missing 'reqData' field")
        return

    # category = reqData.get("category", "") 
    org_id= reqData.get("org_id", "0")  
    q_id = reqData.get("question_id", "")  
    user_answer = reqData.get("user_answer", "")  
    state = reqData.get("state", "draft")  


    if not all([q_id, user_answer, org_id, state]):
        await emitter.error("🚩 The payload 'reqData must contain these: category, q_id, user_answer, org_id, and state'")
        return    

    question_registry = QuestionRegistry(data_dir)

    try:
        # ✅ Initialize Answer Service (uses S3)
        answer_service = AnswerService(s3_client)

        # ✅ Persist to S3
        answer_service.upsert_answer(
            org_id=org_id,
            audit_id=0,
            question_id=q_id,
            answer=user_answer,
            state=state
        )

        await emitter.info(
            "🧱 Save Answer",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "question_path": question_registry.get_question_path(q_id),
                "status": True,
                "saved_to": "s3"
            }
        )

    except Exception as e:
        await emitter.error(f"❌ Failed to save answer: {str(e)}",         
                            payload = {
                                                        "reqType": request.reqType, 
                                                        "reqSubType": request.reqSubType
                                                        })

# ---------------------------------------------------
#   REQUEST 2:
# 
#   TODO: audit_id -> 0 (hard-coded)
# 
# ---------------------------------------------------
@route("AI-ASSESSMENT-REQ", "FETCH-ANSWERS")
async def fetch_answers(
    ws,
    client_id,
    request,
    manager
):
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    # 🔴 Validate request
    if not reqData:
        await emitter.error("🚩 Missing 'reqData' field")
        return

    org_id = reqData.get("org_id")
    audit_id = reqData.get("audit_id", "0")  # default for now

    if not org_id:
        await emitter.error("🚩 'org_id' is required")
        return

    try:
        # ✅ Initialize service
        answer_service = AnswerService(s3_client)

        # ✅ Fetch from S3
        answers = answer_service.get_all_answers(
            org_id=org_id,
            audit_id=0
        )

        # 🔹 Optional: convert list → map (UI friendly)
        answers_map = {
            item["question_id"]: item
            for item in answers
        }

        # ✅ Emit success response
        await emitter.info(
            "📥 Fetch Answers",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                "org_id": org_id,
                "audit_id": audit_id,
                "total": len(answers_map),
                "answers": answers_map
            }
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed to fetch answers: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "org_id": org_id,
                "audit_id": audit_id
            }
        )


@route("AI-ASSESSMENT-REQ", "SAVE-ORG-PROFILE")
async def save_org_profile(ws, client_id, request, manager):

    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    # 🔴 Validate
    if not reqData:
        await emitter.error("🚩 Missing 'reqData'")
        return

    org_id = reqData.get("org_id")
    name = reqData.get("name")
    email = reqData.get("email")
    status = reqData.get("status", "pending")

    if not all([org_id, name, email]):
        await emitter.error(
            "🚩 Required: org_id, name, email"
        )
        return

    try:
        service = OperationalService(s3_client)

        result = service.upsert_org_profile(
            org_id=org_id,
            name=name,
            email=email,
            status=status
        )

        await emitter.info(
            "🏢 Save Org Profile",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                "org_id": org_id,
                "data": result
            }
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed to save org profile: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType
            }
        )


@route("AI-ASSESSMENT-REQ", "FETCH-ORGANIZATIONS")
async def fetch_organizations(ws, client_id, request, manager):

    emitter = EventEmitter(websocket=ws)

    try:
        service = OperationalService(s3_client)

        orgs = service.get_all_organizations()

        await emitter.info(
            "🏢 Fetch Organizations",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                "total": len(orgs),
                "organizations": orgs
            }
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed to fetch organizations: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType
            }
        )



# @route("AI-ASSESSMENT-REQ", "FETCH-GAP-ANALYSIS")
# async def fetch_gap_analysis(
#     ws,
#     client_id,
#     request,
#     manager
# ):
#     emitter = EventEmitter(websocket=ws)

#     reqData = request.reqData

#     # 🔴 Validate request
#     if not reqData:
#         await emitter.error("🚩 Missing 'reqData' field")
#         return

#     org_id = reqData.get("org_id")
#     audit_id = reqData.get("audit_id")

#     if not all([org_id, audit_id]):
#         await emitter.error("🚩 'org_id' and 'audit_id' are required")
#         return

#     try:
#         # ✅ Use S3 client from manager
#         # s3_client = manager.s3_client

#         # ✅ Use ReportService (correct service for gap analysis)
#         report_service = ReportService(s3_client)

#         # ✅ Fetch gap analysis data from S3
#         results = report_service.get_gap_report(
#             org_id=org_id,
#             audit_id=audit_id
#         )

#         # 🔹 Convert list → map (UI friendly)
#         results_map = {
#             item.get("question_id"): item
#             for item in results
#             if item.get("question_id")
#         }

#         # ✅ Emit success response
#         await emitter.info(
#             "📥 Fetch gap analysis",
#             payload={
#                 "reqType": request.reqType,
#                 "reqSubType": request.reqSubType,
#                 "status": True,
#                 "org_id": org_id,
#                 "audit_id": audit_id,
#                 "total": len(results_map),
#                 "data": results_map
#             }
#         )

#     except Exception as e:
#         await emitter.error(
#             f"❌ Failed to fetch gap analysis: {str(e)}",
#             payload={
#                 "reqType": request.reqType,
#                 "reqSubType": request.reqSubType,
#                 "org_id": org_id,
#                 "audit_id": audit_id
#             }
#         )


@route("AI-ASSESSMENT-REQ", "FETCH-GAP-ANALYSIS")
@route("AI-ASSESSMENT-REQ", "FETCH-FULL-AUDIT")
async def fetch_full_audit(ws, client_id, request, manager):

    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    if not reqData:
        await emitter.error("🚩 Missing 'reqData'")
        return

    org_id = reqData.get("org_id")
    audit_id = reqData.get("audit_id", "0")

    if not org_id:
        await emitter.error("🚩 Missing org_id")
        return

    try:
        report_service = ReportService(s3_client)

        result = report_service.get_full_audit_view(org_id, audit_id)

        await emitter.info(
            "📊 Full Audit View",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                **result
            }
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType
            }
        )


@route("AI-ASSESSMENT-REQ", "SAVE-REVIEW")
async def save_review(ws, client_id, request, manager):

    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    # 🔴 Validate
    if not reqData:
        await emitter.error("🚩 Missing 'reqData'")
        return

    org_id = reqData.get("org_id")
    audit_id = reqData.get("audit_id", "0")
    question_id = reqData.get("question_id")
    review_state = reqData.get("review_state")
    reviewer_comment = reqData.get("reviewer_comment")

    if not all([org_id, audit_id, question_id, review_state]):
        await emitter.error(
            "🚩 Required: org_id, audit_id, question_id, review_state"
        )
        return

    try:
        # 🔹 Services
        auditor_service = AuditorService(s3_client)
        answer_service = AnswerService(s3_client)

        # 🔹 Fetch answer to get version
        answer = answer_service.get_answer(org_id, audit_id, question_id)

        if not answer:
            await emitter.error("❌ Answer not found for question")
            return

        version = answer.get("version", 0)

        # 🔹 Build feedback payload
        feedback_payload = {
            "version": version,
            "auditor_id": client_id or "auditor_unknown",
            "review_state": review_state,
            "summary": reviewer_comment,
            "feedback": []  # keeping structured field for future
        }

        # 🔹 Save to S3
        result = auditor_service.update_feedback(
            org_id=org_id,
            audit_id=audit_id,
            question_id=question_id,
            feedback=feedback_payload
        )

        # ✅ Success response
        await emitter.info(
            "🧑‍⚖️ Save Review",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "status": True,
                "org_id": org_id,
                "audit_id": audit_id,
                "question_id": question_id,
                "review_state": result.get("review_state"),
                "reviewed_version": result.get("reviewed_version")
            }
        )

    except Exception as e:
        await emitter.error(
            f"❌ Failed to save review: {str(e)}",
            payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "org_id": org_id,
                "audit_id": audit_id,
                "question_id": question_id
            }
        )




# ---------------------------------------------------
#   REQUEST 2:
# ---------------------------------------------------
@route("SUPPORTWIZ_USER_REQS", "SUMMARY-SEMANTIC-SEARCH")
async def search_s_kbindex_by_context(
   ws, 
   client_id, 
   request, 
   manager
) -> Dict[str, Any]:
    """
    Semantic / similarity search on KB questions by context text.
    Optionally creates a cluster.
    """

    emitter = EventEmitter(websocket=ws)
    await emitter.info("💬 Connected (Context: SupportWiz)" )

    reqData = request.reqData
    
    if not reqData:     
        await emitter.error("🚩 Missing 'reqData' field")
        return

    # index_name = reqData.get("index_name", "") 
    QUERY = reqData.get("context", "") 
    COUNT = reqData.get("count", 10)

    if not all([QUERY, COUNT]):
        await emitter.error("🚩 The payload 'reqData must contain these: QUERY and COUNT'")
        return


    supportwiz_response = engine.semantic_summary(QUERY, COUNT)

    payload = {
        "reqType": request.reqType,
        "reqSubType": request.reqSubType,
    }

    if isinstance(supportwiz_response, dict):
        payload.update(supportwiz_response)
    elif isinstance(supportwiz_response, list):
        payload["data"] = supportwiz_response
    else:
        payload["data"] = supportwiz_response

 
    await emitter.info("🧱 Summaries:", 
            payload=payload
    )






# ---------------------------------------------------
#   REQUEST 3:
# ---------------------------------------------------
@route("SUPPORTWIZ_USER_REQS", "USER-ANSWER-GAP-ANALYSIS")
async def answer_gap_analysis(ws, client_id, request, manager):
           
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData
    
    if not reqData:     
        await emitter.error("🚩 Missing 'reqData' field")
        return

    # category = reqData.get("category", "") 
    customer_id =reqData.get("customer_id", "")  
    index_name = reqData.get("index_name", "") 
    question = reqData.get("question", "") 
    question_id = reqData.get("question_id", "") 
    user_answer = reqData.get("user_answer", "") 


    if not all([index_name, question, user_answer]):
        await emitter.error("🚩 The payload 'reqData must contain these: question, index_name, user_answer")
        return

    # -----------------------------------------------------------------------------------
    # Step 1: Fetch Data
    # -----------------------------------------------------------------------------------

    supportwiz_response = engine.semantic_summary(question, 10)



    """
      {
        payload: {
        "summaries": [
              {
                "text": "This cluster explores the factors contributing to failure rates ...",
                "id": "278c4447c7eef12e5eebf512bad1d5b7481bb2cf"
              },
              ...
              ]
          }
      }
    """


    # -----------------------------------------------------------------------------------
    # Step 2: Synthesize
    # -----------------------------------------------------------------------------------

    payload = {}

    if isinstance(supportwiz_response, dict):
        payload.update(supportwiz_response)
    elif isinstance(supportwiz_response, list):
        payload["data"] = supportwiz_response
    else:
        payload["data"] = supportwiz_response


    def summaries_to_text(summaries: List[Dict[str, Any]]) -> str:
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

    summaries_text = summaries_to_text(payload["results"])


    # await emitter.info("🧱 Search Data Structure:", 
    #         payload=summaries_text
    #   )    


    # -----------------------------------------------------------------------------------
    # Step 3: Find Gap
    # -----------------------------------------------------------------------------------

    # Build the prompt (clean + deterministic)
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

    # Assemble the chain
    parser = JsonOutputParser(pydantic_object=SynthesisGapOutput)

    chain = (
        prompt.partial(
            format_instructions=parser.get_format_instructions()
        )
        | llm_client
        | parser
    )


    ai_summary = chain.invoke({
        "content": summaries_text,
        "question": question,
        "user_answer": user_answer,
        "question_intent": "Evaluate implementation gaps between the user's answer and the authoritative synthesized answer derived from the knowledge base"
    })

  
    
    # always - reqType and reqSubType are inside the payload.
    payload = {
        "reqType": request.reqType,
        "reqSubType": request.reqSubType,
        "customer_id" : customer_id,
        "question_id": question_id,   
        "data": ai_summary
    }

    
    await emitter.info("🧱 Gap Analysis:", 
          payload=payload            
    )    



class SynthesisGapOutput(BaseModel):

    synthesized_summary: str = Field(
        description=(
            "Authoritative, concise answer synthesized strictly from the retrieved "
            "context. This represents the reference answer used for gap evaluation."
        )
    )

    key_themes: List[str] = Field(
        description=(
            "Distinct, high-level concepts explicitly present in the retrieved "
            "context and reflected in the synthesized_summary."
        ),
        min_items=1
    )

    user_gap: List[str] = Field(
        description=(
            "Concrete, factual gaps, omissions, or inaccuracies in the user answer "
            "when compared strictly against the synthesized_summary. "
            "Each item must describe a single, specific gap."
        )
    )

    insights: List[str] = Field(
        description=(
            "Actionable, improvement-oriented guidance that helps the user close "
            "the identified gaps. Each insight should directly correspond to one "
            "or more items in user_gap."
        )
    )

    match_score: confloat(ge=0.0, le=1.0) = Field(
        description=(
            "Numerical alignment score between the user answer and the synthesized_summary. "
            "0.0 indicates no meaningful alignment. "
            "1.0 indicates full alignment with no substantive gaps. "
            "Score must be derived solely from content coverage and correctness."
        )
    )
 

 

# @route("SUPPORTWIZ_USER_REQS", "QUESTION-SEMANTIC-SEARCH")
# async def search_q_kbindex_by_context(
#    ws, 
#    client_id, 
#    request, 
#    manager
# ) -> Dict[str, Any]:
#     """
#     Semantic / similarity search on KB questions by context text.
#     Optionally creates a cluster.
#     """

#     emitter = EventEmitter(websocket=ws)
#     await emitter.info("💬 Connected (Context: SupportWiz)" )

#     reqData = request.reqData
    
#     if not reqData:     
#         await emitter.error("🚩 Missing 'reqData' field")
#         return

#     index_name = reqData.get("index_name", "") 
#     context = reqData.get("context", "") 
#     count = reqData.get("count", 10)
#     create_cluster = reqData.get("create_cluster", False)  

#     if not all([index_name, context]):
#         await emitter.error("🚩 The payload 'reqData must contain these: context and index_name'")
#         return   
 
#     payload_to_support_wiz={
#               "reqType": request.reqType,
#               "reqSubType": request.reqSubType,
#               "reqData": {
#                 "index_name": index_name,
#                 "context": context,
#                 "count": count,
#                 "create_cluster": create_cluster
#               }
#           }

#     supportwiz_response =    await support_client.send_request(payload_to_support_wiz)


#     payload = {
#         "reqType": request.reqType,
#         "reqSubType": request.reqSubType,
#     }

#     if isinstance(supportwiz_response, dict):
#         payload.update(supportwiz_response)
#     elif isinstance(supportwiz_response, list):
#         payload["data"] = supportwiz_response
#     else:
#         payload["data"] = supportwiz_response

 
#     await emitter.info("🧱 Questions:", 
#             payload=payload
#     )
 
