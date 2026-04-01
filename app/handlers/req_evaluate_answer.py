from app.engine.emitter import EventEmitter
from app.engine.message_router import route
from app.handlers.common import data_dir
from app.procs.anchor_match.question_evaluator import QuestionEvaluator
from app.procs.anchor_match.question_faiss_index import QuestionFaissIndex
from app.procs.anchor_match.question_registry import QuestionRegistry
from app.procs.embeddings import EmbeddingModel


@route("AI-ASSESSMENT-REQ", "EVALUATE-ANSWER")
async def evaluate_answer(ws, client_id, request, manager):
    emitter = EventEmitter(websocket=ws)

    reqData = request.reqData

    if not reqData:
        await emitter.error("🚩 Missing 'reqData' field")
        return

    q_id = reqData.get("q_id", "")
    user_answer = reqData.get("user_answer", "")

    if not all([q_id, user_answer]):
        await emitter.error(
            "🚩 The payload 'reqData must contain these: q_id, user_answer'"
        )
        return

    embedder = EmbeddingModel()
    question_registry = QuestionRegistry(data_dir)

    index = QuestionFaissIndex(q_id, embedder, question_registry)

    if index.exists():
        await emitter.info(f"--Index for {q_id} exists. Loading")
        index.load()
    else:
        await emitter.warn(f"--Index for {q_id} Not exists. Building")

    evaluator = QuestionEvaluator(
        q_id, embedding_model=embedder, registry=question_registry
    )

    evaluation = evaluator.evaluate(user_answer)

    await emitter.info(
        "🧱 Answer Assessment",
        payload={
            "reqType": request.reqType,
            "reqSubType": request.reqSubType,
            "Assessment": evaluation,
        },
    )
