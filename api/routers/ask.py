from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ai.answer import Answer, ask
from api.deps import get_session

router = APIRouter()


class AskRequest(BaseModel):
    question: str


@router.post("/ask", response_model=Answer)
def ask_question(request: AskRequest, session: Session = Depends(get_session)) -> Answer:
    return ask(session, request.question)
