from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_url: Mapped[str] = mapped_column(String(500), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    analysis: Mapped["Analysis | None"] = relationship(back_populates="job", uselist=False)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("analysis_jobs.id"), unique=True, index=True)

    owner: Mapped[str] = mapped_column(String(200))
    repo: Mapped[str] = mapped_column(String(200))
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    detected_stack: Mapped[list] = mapped_column(JSON, default=list)
    services: Mapped[list] = mapped_column(JSON, default=list)
    env_vars: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    architecture: Mapped[dict] = mapped_column(JSON, default=dict)
    readiness_score: Mapped[int] = mapped_column(Integer, default=0)
    generated_zerops_yaml: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[AnalysisJob] = relationship(back_populates="analysis")


class ErrorLog(Base):
    __tablename__ = "error_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
