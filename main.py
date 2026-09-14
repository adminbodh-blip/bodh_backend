import os
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, Session, create_engine, select
import random


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:V7337mgdMDtB2l8c@db.uhnarkmghbebahlaotxk.supabase.co:5432/postgres")
engine = create_engine(DATABASE_URL, echo=False)

app = FastAPI(title="JEE Secure CBT Engine",debug=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Database Models ---
class ExamPaperDB(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_name: str
    paper_title: str
    year: int
    paper_number: int

class QuestionDB(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="exampaperdb.id")
    subject: str
    section_name: str
    question_number: int
    question_type: str
    topic_tags: str
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    positive_marks: int
    negative_marks: int
    has_diagram: bool
    diagram_url: str
    

def get_session():
    with Session(engine) as session:
        yield session

# --- Public Sanitized Models (No correct_answer exposed) ---
class SanitizedQuestion(SQLModel):
    id: int
    subject: str
    section_name: str
    question_number: int
    question_type: str
    topic_tags: List[str]
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    has_diagram: bool
    diagram_url: str
    positive_marks: int
    negative_marks: int
    source_tag: Optional[str] = None

class TestPayload(SQLModel):
    title: str
    duration_seconds: int
    questions: List[SanitizedQuestion]

class SubmissionPayload(SQLModel):
    responses: Dict[int, str]  # { question_id: "A" }

# --- API Endpoints ---

@app.get("/api/exam/guest-test", response_model=TestPayload)
def get_guest_test(
    subject: str, 
    target_marks: int = 50, 
    session: Session = Depends(get_session)
):
    """Random questions across any past year until target marks are reached."""
    valid_subjects = ["Physics", "Chemistry", "Math"]
    matched_subject = next((s for s in valid_subjects if s.lower() == subject.lower()), None)
    if not matched_subject:
        raise HTTPException(status_code=400, detail="Invalid subject selection.")

    # Join QuestionDB with ExamPaperDB to pull paper title and year metadata
    statement = (
        select(QuestionDB, ExamPaperDB)
        .join(ExamPaperDB, QuestionDB.paper_id == ExamPaperDB.id)
        .where(QuestionDB.subject == matched_subject)
    )
    all_pairs = session.exec(statement).all()

    if not all_pairs:
        raise HTTPException(status_code=404, detail="No questions found for this subject.")

    # Shuffle question pool randomly across all years
    random.shuffle(all_pairs)

    # Accumulate questions until target_marks is met
    accumulated_marks = 0
    selected_pairs = []
    for q, paper in all_pairs:
        selected_pairs.append((q, paper))
        accumulated_marks += q.positive_marks
        if accumulated_marks >= target_marks:
            break

    sanitized = [
        SanitizedQuestion(
            id=q.id,
            subject=q.subject,
            section_name=q.section_name,
            question_number=idx + 1,
            question_type=q.question_type,
            topic_tags=q.topic_tags.split(",") if q.topic_tags else [],
            question_text=q.question_text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            has_diagram=q.has_diagram,
            diagram_url=q.diagram_url,
            positive_marks=q.positive_marks,
            negative_marks=q.negative_marks,
            source_tag=f"{paper.paper_title}"
        )
        for idx, (q, paper) in enumerate(selected_pairs)
    ]

    return TestPayload(
        title=f"Practice: {matched_subject} (~{accumulated_marks} Marks)",
        duration_seconds=30 * 60,
        questions=sanitized
    )


@app.get("/api/exam/full-test", response_model=TestPayload)
def get_full_test(year: int, paper_number: int = 1, subject: Optional[str] = "All", session: Session = Depends(get_session)):
    """Full 3-hour exam simulation (requires user login on frontend)."""
    paper = session.exec(
        select(ExamPaperDB).where(
            ExamPaperDB.year == year,
            ExamPaperDB.paper_number == paper_number
        )
    ).first()

    if not paper:
        raise HTTPException(status_code=404, detail="Exam paper not found.")

    query = select(QuestionDB).where(QuestionDB.paper_id == paper.id)
    if subject and subject != "All":
        query = query.where(QuestionDB.subject == subject)

    questions = session.exec(query).all()

    sanitized = [
        SanitizedQuestion(
            id=q.id,
            subject=q.subject,
            section_name=q.section_name,
            question_number=q.question_number,
            question_type=q.question_type,
            topic_tags=q.topic_tags.split(",") if q.topic_tags else [],
            question_text=q.question_text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            has_diagram=q.has_diagram,
            diagram_url=q.diagram_url,
            positive_marks=q.positive_marks,
            negative_marks=q.negative_marks,
            source_tag=f"{paper.paper_title}"
        )
        for q in questions
    ]

    duration = 180 * 60 if subject == "All" else 60 * 60
    return TestPayload(
        title=f"{paper.paper_title} - {subject}",
        duration_seconds=duration,
        questions=sanitized
    )

@app.post("/api/exam/evaluate")
def evaluate_exam(payload: SubmissionPayload, session: Session = Depends(get_session)):
    """Evaluates user responses against the secure database records."""
    question_ids = list(payload.responses.keys())
    if not question_ids:
        return {"total_score": 0, "correct": 0, "incorrect": 0, "subject_scores": {}}

    db_questions = session.exec(
        select(QuestionDB).where(QuestionDB.id.in_(question_ids))
    ).all()
    db_map = {q.id: q for q in db_questions}

    total_score = 0
    correct_count = 0
    incorrect_count = 0
    subject_scores = {}

    for q_id, user_ans in payload.responses.items():
        q = db_map.get(int(q_id))
        if not q:
            continue

        subj = q.subject
        if subj not in subject_scores:
            subject_scores[subj] = {"score": 0, "correct": 0, "total": 0}
        subject_scores[subj]["total"] += 1

        clean_user = user_ans.strip().upper()
        clean_correct = q.correct_answer.strip().upper()

        if clean_user:
            if clean_user == clean_correct:
                total_score += q.positive_marks
                correct_count += 1
                subject_scores[subj]["score"] += q.positive_marks
                subject_scores[subj]["correct"] += 1
            else:
                total_score += q.negative_marks
                incorrect_count += 1
                subject_scores[subj]["score"] += q.negative_marks

    return {
        "total_score": total_score,
        "correct": correct_count,
        "incorrect": incorrect_count,
        "subject_scores": subject_scores
    }