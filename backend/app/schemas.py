from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl


class JobCreate(BaseModel):
    repo_url: str = Field(..., examples=["https://github.com/tiangolo/full-stack-fastapi-template"])


class JobOut(BaseModel):
    id: int
    repo_url: str
    status: str
    error: str | None = None
    error_hint: str | None = None
    created_at: datetime
    updated_at: datetime
    analysis_id: int | None = None


class AnalysisOut(BaseModel):
    id: int
    owner: str
    repo: str
    default_branch: str
    description: str | None
    detected_stack: list
    services: list
    env_vars: list
    risks: list
    checks: list
    architecture: dict
    readiness_score: int
    generated_zerops_yaml: str
    summary: str
    file_count: int
    created_at: datetime


class DiagnoseIn(BaseModel):
    logs: str = Field(..., min_length=3, max_length=20000)
    context: str = Field(default="", max_length=5000)


class DiagnoseOut(BaseModel):
    provider: str
    diagnosis: str


class LogOut(BaseModel):
    id: int
    job_id: int | None = None
    message: str
    hint: str | None = None
    created_at: datetime


class QuickAnalysisIn(BaseModel):
    repo_url: str = Field(..., examples=["https://github.com/tiangolo/full-stack-fastapi-template"])


class QuickAnalysisOut(BaseModel):
    owner: str
    repo: str
    default_branch: str
    description: str | None
    detected_stack: list
    services: list
    env_vars: list
    risks: list
    checks: list
    architecture: dict
    readiness_score: int
    generated_zerops_yaml: str | None = None
    summary: str
    file_count: int
