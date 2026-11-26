# E4/E5/E6 session management + grading + reporting.
#
# E4 grading: reuses AssessmentEngine.grade_math or the course checkpoint judge.
# E5 sessions: K1 text version, persistence only (no LiveKit token issuance).
# E6 report: aligned with lesson_report fields (attendance/pages_viewed/quiz_stat/question_stat/weak_points).
# Abnormal sessions write no snapshot (dirty-data fields=null), following the LinguaKids constraint.

from __future__ import annotations

import logging
from typing import Any

from .models import AnswerRecord, ClassReport, ClassSession, new_id, now_ts
from .store import ClassroomStore

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, store: ClassroomStore) -> None:
        self.store = store

    def create_session(self, class_id: str, code: str, student_id: str) -> ClassSession:
        sess = ClassSession(
            session_id=new_id("ses_"), class_id=class_id, code=code,
            student_id=student_id, status="active", started_at=now_ts(),
        )
        self.store.save_session(sess.to_dict())
        logger.info("session: created session=%s class=%s student=%s", sess.session_id, class_id, student_id)
        return sess

    def get_session(self, session_id: str) -> ClassSession | None:
        data = self.store.get_session(session_id)
        if not data:
            return None
        return self._hydrate(data)

    def record_answer(
        self, session_id: str, question_id: str, student_answer: str,
        correct: bool, feedback: str = "", detail: str = "",
    ) -> AnswerRecord:
        sess = self.get_session(session_id)
        rec = AnswerRecord(
            question_id=question_id, student_answer=student_answer,
            correct=correct, feedback=feedback, detail=detail, timestamp=now_ts(),
        )
        if sess:
            sess.answers.append(rec)
            self.store.save_session(sess.to_dict())
        logger.info("session: answer session=%s q=%s correct=%s", session_id, question_id, correct)
        return rec

    def record_page_view(self, session_id: str, page_index: int) -> None:
        sess = self.get_session(session_id)
        if sess and page_index not in sess.pages_viewed:
            sess.pages_viewed.append(page_index)
            self.store.save_session(sess.to_dict())

    def record_question(self, session_id: str) -> None:
        sess = self.get_session(session_id)
        if sess:
            sess.questions_asked += 1
            self.store.save_session(sess.to_dict())

    def finish_session(self, session_id: str, abandoned: bool = False) -> ClassSession | None:
        sess = self.get_session(session_id)
        if not sess:
            return None
        sess.status = "abandoned" if abandoned else "finished"
        sess.finished_at = now_ts()
        sess.abandoned = abandoned
        self.store.save_session(sess.to_dict())
        logger.info("session: finished session=%s status=%s", session_id, sess.status)
        return sess

    def build_report(self, session_id: str) -> ClassReport:
        sess = self.get_session(session_id)
        if not sess:
            # i18n: user-facing
            return ClassReport(
                session_id=session_id, class_id="", student_id="", error="会话不存在",
            )
        # Abnormal sessions write no dirty data: abandoned keeps quiz_stat/question_stat empty
        if sess.abandoned:
            # i18n: user-facing
            return ClassReport(
                session_id=session_id, class_id=sess.class_id, student_id=sess.student_id,
                attendance=self._attendance(sess),
                pages_viewed=sess.pages_viewed,
                quiz_stat={}, question_stat={}, weak_points=[],
                error="会话异常终止, 不写快照",
            )
        correct = sum(1 for a in sess.answers if a.correct)
        total = len(sess.answers)
        quiz_stat = {
            "total": total, "correct": correct,
            "accuracy": round(correct / total, 2) if total else 0.0,
            "details": [a.to_dict() for a in sess.answers],
        }
        question_stat = {"count": sess.questions_asked}
        weak = [a.question_id for a in sess.answers if not a.correct]
        return ClassReport(
            session_id=session_id, class_id=sess.class_id, student_id=sess.student_id,
            attendance=self._attendance(sess),
            pages_viewed=sess.pages_viewed,
            quiz_stat=quiz_stat, question_stat=question_stat,
            weak_points=weak,
        )

    def _attendance(self, sess: ClassSession) -> dict[str, Any]:
        duration = (sess.finished_at or now_ts()) - sess.started_at if sess.started_at else 0
        return {
            "student_id": sess.student_id, "status": sess.status,
            "duration_sec": round(max(0, duration), 1),
            "pages_viewed_count": len(sess.pages_viewed),
        }

    def _hydrate(self, data: dict[str, Any]) -> ClassSession:
        answers = [AnswerRecord(
            question_id=a.get("question_id", ""), student_answer=a.get("student_answer", ""),
            correct=a.get("correct", False), feedback=a.get("feedback", ""),
            detail=a.get("detail", ""), timestamp=a.get("timestamp", 0.0),
        ) for a in data.get("answers", []) if isinstance(a, dict)]
        return ClassSession(
            session_id=data.get("session_id", ""), class_id=data.get("class_id", ""),
            code=data.get("code", ""), student_id=data.get("student_id", ""),
            status=data.get("status", "active"), started_at=data.get("started_at", 0.0),
            finished_at=data.get("finished_at", 0.0),
            pages_viewed=list(data.get("pages_viewed", [])),
            answers=answers, questions_asked=data.get("questions_asked", 0),
            abandoned=data.get("abandoned", False),
        )
