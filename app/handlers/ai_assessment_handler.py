import json
from pathlib import Path
from typing import Dict, List

from app.config import get_config
from app.engine.emitter import EventEmitter
from app.engine.message_router import route

# ---
from app.procs.category_question_loader import \
    CategoryQuestionLoader

from app.procs.anchor_match.question_evaluator import \
    QuestionEvaluator
from app.procs.anchor_match.question_faiss_index import \
    QuestionFaissIndex

from app.procs.anchor_match.question_registry import \
    QuestionRegistry

from app.procs.embeddings import EmbeddingModel


# ------- Specific to AI Assessment

cfg = get_config()
data_dir = cfg.ai_assessment.data_dir
indexes_dir = cfg.ai_assessment.indexes_dir
# ---------------------------------------------------
#   REQUEST 1:
# ---------------------------------------------------
@route("AI-ASSESSMENT-REQ", "GET-CATEGORIES")
async def get_assessment_categories(ws, 
                                         client_id, 
                                         request, 
                                         manager 
                                         ):
         
  
    emitter = EventEmitter(websocket=ws)
    await emitter.info("💬 Connected (Context: AI Assessment)", 
        payload={"data_dir" : data_dir} )

    
    if not data_dir:
        await emitter.error("🚩 Missing data_dir")
        return       


    # load categories
    category_question_loader = CategoryQuestionLoader(data_dir)

    
    # Final Result of the execution of firmographic search
    await emitter.info("🧱 Assessment Categories", 
        payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "Categories" : category_question_loader.list_categories()
            }
        )


# ---------------------------------------------------
#   REQUEST 2:
# ---------------------------------------------------
@route("AI-ASSESSMENT-REQ", "GET-QUESTIONS")
async def get_questions_by_category(ws, 
                                         client_id, 
                                         request, 
                                         manager
                                         ):
         
  
    emitter = EventEmitter(websocket=ws)
    await emitter.info("💬 Connected (Context: AI Assessment)", 
    payload={"data_dir" : data_dir} )

    
    reqData = request.reqData
    
    if not reqData:     
        await emitter.error("🚩 Missing 'reqData' field")
        return

    category = reqData.get("category", "") 

    if not all([category]):
        await emitter.error("🚩 The payload 'reqData must contain these: category'")
        return    

    
    # load categories
    category_question_loader = CategoryQuestionLoader(data_dir)
    

    # Final Result
    await emitter.info("🧱 Questions", 
        payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "Questions" : category_question_loader.load_category(category)
            }
        )



# ---------------------------------------------------
#   REQUEST 3:
# ---------------------------------------------------
@route("AI-ASSESSMENT-REQ", "EVALUATE-ANSWER")
async def evaluate_answer(ws, 
                                         client_id, 
                                         request, 
                                         manager
                                         ):
         
  
    emitter = EventEmitter(websocket=ws)


    reqData = request.reqData
    
    if not reqData:     
        await emitter.error("🚩 Missing 'reqData' field")
        return

    # category = reqData.get("category", "") 
    q_id = reqData.get("q_id", "")  
    user_answer = reqData.get("user_answer", "")  


    if not all([q_id, user_answer]):
        await emitter.error("🚩 The payload 'reqData must contain these: category, q_id, user_answer'")
        return    

    embedder = EmbeddingModel()
    question_registry = QuestionRegistry(data_dir)
    

    index = QuestionFaissIndex(q_id, embedder, question_registry)
    
    # await emitter.info("🧱 Answer Assessment", 
    #         payload=index.exists())

    if index.exists():
        await emitter.info(f"--Index for {q_id} exists. Loading")
        index.load()
    else:
        emitter.warn(f"--Index for {q_id} Not exists. Building")


    # -------- Evaluate ------------
    evaluator = QuestionEvaluator( q_id, embedding_model=embedder, registry=question_registry)

    evaluation = evaluator.evaluate(user_answer)



    await emitter.info("🧱 Answer Assessment", 
        payload={
                "reqType": request.reqType,
                "reqSubType": request.reqSubType,
                "Assessment" : evaluation
            }
        )


''' 
# ---------------------------------------------------
#   REQUEST 4:
# ---------------------------------------------------
@route("AI-ASSESSMENT-REQ", "LLM-SYNTHESIZE-BY-CATEGORY")
async def ai_summary_by_category(ws, 
                                         client_id, 
                                         request, 
                                         manager
                                         ):
         
  
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData
    
    if not reqData:     
        await emitter.error("🚩 Missing 'reqData' field")
        return

    # category = reqData.get("category", "") 
    category = reqData.get("category", "")  
    evaluations = reqData.get("evaluations", [])

    if not all([category, evaluations]):
        await emitter.error("🚩 The payload 'reqData must contain these: category, evalutions'")
        return

    import random
    choices = [30, 75, 80, 90]
    confidence = random.choice(choices)

    hard_coded_summary = {
      "category": category,
      "summary": {
        "confidence": confidence,
        "summary_text": "The tool demonstrates a reasonably well-defined architectural control model with clear intent to enforce policies at specific integration points. Preventive and detective capabilities are articulated, particularly around API-level enforcement and request inspection. However, certain enforcement paths rely heavily on downstream detection rather than upfront prevention, and coverage gaps exist across non-API execution paths. Overall, the architecture reflects a mature design direction but requires further clarity and consistency in enforcement guarantees.",
        "strengths": [
          "Clearly identifies primary enforcement points at the API gateway and request processing layers",
          "Demonstrates awareness of the distinction between preventive, detective, and observability controls",
          "Acknowledges architectural limitations rather than over-claiming full coverage",
          "Provides a modular control model that can be extended across additional integration points"
        ],
        "gaps": [
          "Enforcement behavior is not consistently described across all access paths (e.g., client-side and internal service-to-service calls)",
          "Some controls rely on post-event detection rather than inline prevention",
          "Lack of concrete examples illustrating enforcement behavior during partial failures or degraded modes"
        ],
        "risks": [
          "Potential exposure if non-API data flows bypass the primary enforcement layer",
          "Risk of false sense of protection if enforcement coverage assumptions are not validated",
          "Operational risk if observability signals are treated as preventive guarantees"
        ]
      }
    }

    # ...

    


    await emitter.info("🧱 AU Summary", 
    payload={
            "reqType": request.reqType,
            "reqSubType": request.reqSubType,            
            "AISummary" : hard_coded_summary
        }
    )

    '''