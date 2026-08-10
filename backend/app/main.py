from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal, init_db
from .diagnostics import diagnose
from .models import Analysis, AnalysisJob, ErrorLog
from .schemas import AnalysisOut, DiagnoseIn, DiagnoseOut, JobCreate, JobOut, LogOut
from pathlib import Path
from .config import get_settings
from .github_client import GitHubClient
from .analyzer import detect
from .zerops_generator import generate_zerops_yaml
from .schemas import QuickAnalysisIn, QuickAnalysisOut
from fastapi.responses import StreamingResponse
import queue
import threading
import json
from .github_client import get_metrics


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Check DB connectivity and surface a clear message for operators/devs.
    try:
        from .db import test_db_connection
        ok, msg = test_db_connection()
        if not ok:
            print("WARNING: Database connectivity check failed:", msg)
            print("Verify DATABASE_URL and that the database is reachable from this host.")
        else:
            print("Database connectivity: OK")
    except Exception as exc:
        print("Database connectivity check skipped due to error:", exc)
    yield


app = FastAPI(
    title="InfraPilot AI API",
    version="1.0.0",
    description="AI Forward Deployment Engineer backend",
    lifespan=lifespan,
)

settings = get_settings()
# Configure CORS: prefer configured origins, otherwise allow common local dev origin.
allow_origins = settings.cors_origin_list if settings.cors_origin_list else ["http://localhost:5173"]
print("CORS allow_origins:", allow_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "name": "InfraPilot AI",
        "tagline": "Your AI Forward Deployment Engineer",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "infrapilot-api"}


def job_out(job: AnalysisJob) -> JobOut:
    return JobOut(
        id=job.id,
        repo_url=job.repo_url,
        status=job.status,
        error=job.error,
        error_hint=getattr(job, "error_hint", None),
        created_at=job.created_at,
        updated_at=job.updated_at,
        analysis_id=job.analysis.id if job.analysis else None,
    )


@app.post("/api/jobs", response_model=JobOut, status_code=202)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    if "github.com/" not in payload.repo_url:
        raise HTTPException(400, "InfraPilot MVP currently analyzes GitHub repositories.")
    job = AnalysisJob(repo_url=payload.repo_url.strip(), status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job_out(job)


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job_out(job)


@app.get("/api/analyses/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: int, db: Session = Depends(get_db)):
    item = db.get(Analysis, analysis_id)
    if not item:
        raise HTTPException(404, "Analysis not found")
    return AnalysisOut(
        id=item.id,
        owner=item.owner,
        repo=item.repo,
        default_branch=item.default_branch,
        description=item.description,
        detected_stack=item.detected_stack,
        services=item.services,
        env_vars=item.env_vars,
        risks=item.risks,
        checks=item.checks,
        architecture=item.architecture,
        readiness_score=item.readiness_score,
        generated_zerops_yaml=item.generated_zerops_yaml,
        summary=item.summary,
        file_count=item.file_count,
        created_at=item.created_at,
    )


@app.get("/api/logs", response_model=list[LogOut])
def get_logs(db: Session = Depends(get_db)):
    items = db.execute(select(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(50)).scalars().all()
    return [LogOut(id=i.id, job_id=i.job_id, message=i.message, hint=i.hint, created_at=i.created_at) for i in items]


@app.post("/api/diagnose", response_model=DiagnoseOut)
def diagnose_endpoint(payload: DiagnoseIn):
    provider, text = diagnose(payload.logs, payload.context)
    return DiagnoseOut(provider=provider, diagnosis=text)


@app.get("/api/demo")
def demo():
    return {
        "repo": "https://github.com/tiangolo/full-stack-fastapi-template",
        "sample_log": "ERROR: sqlalchemy.exc.OperationalError: connection refused while connecting to DATABASE_URL",
    }


@app.post("/api/analyze-sync", response_model=QuickAnalysisOut)
def analyze_sync(payload: QuickAnalysisIn):
    """Perform a fast, in-memory analysis and return results immediately. Does not persist to the DB."""
    repo = payload.repo_url
    try:
        client = GitHubClient()
        snapshot = client.snapshot(repo)
        result = detect(snapshot)
        generated_yaml = generate_zerops_yaml(result)

        stack_names = [s["name"] for s in result["signals"]]
        summary = (
            f"Detected {', '.join(stack_names[:6]) or 'an application runtime'} across "
            f"{len(snapshot.files)} repository files. InfraPilot inferred "
            f"{len(result['services'])} deployable service(s) and calculated a "
            f"{result['readiness_score']}/100 readiness score."
        )

        return QuickAnalysisOut(
            owner=snapshot.owner,
            repo=snapshot.repo,
            default_branch=snapshot.default_branch,
            description=snapshot.description,
            detected_stack=result['signals'],
            services=result['services'],
            env_vars=result['env_vars'],
            risks=result['risks'],
            checks=result['checks'],
            architecture=result['architecture'],
            readiness_score=result['readiness_score'],
            generated_zerops_yaml=generated_yaml,
            summary=summary,
            file_count=len(snapshot.files),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/analyze-stream")
def analyze_stream(repo_url: str):
    q = queue.Queue()

    def progress_callback(msg: dict):
        try:
            q.put({"type": "progress", "payload": msg})
        except Exception:
            pass

    def runner():
        try:
            client = GitHubClient()
            q.put({"type": "progress", "payload": {"stage": "fetch_start"}})
            snapshot = client.snapshot(repo_url, progress_callback=progress_callback)
            q.put({"type": "progress", "payload": {"stage": "fetch_done", "files": len(snapshot.files)}})
            q.put({"type": "progress", "payload": {"stage": "detect_start"}})
            result = detect(snapshot)
            generated = generate_zerops_yaml(result)
            stack_names = [s["name"] for s in result["signals"]]
            summary = (
                f"Detected {', '.join(stack_names[:6]) or 'an application runtime'} across "
                f"{len(snapshot.files)} repository files. InfraPilot inferred "
                f"{len(result['services'])} deployable service(s) and calculated a "
                f"{result['readiness_score']}/100 readiness score."
            )
            payload = {
                "owner": snapshot.owner,
                "repo": snapshot.repo,
                "default_branch": snapshot.default_branch,
                "description": snapshot.description,
                "detected_stack": result['signals'],
                "services": result['services'],
                "env_vars": result['env_vars'],
                "risks": result['risks'],
                "checks": result['checks'],
                "architecture": result['architecture'],
                "readiness_score": result['readiness_score'],
                "generated_zerops_yaml": generated,
                "summary": summary,
                "file_count": len(snapshot.files),
            }
            q.put({"type": "done", "payload": payload})
        except Exception as exc:
            q.put({"type": "error", "payload": str(exc)})
        finally:
            q.put({"type": "end"})

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()

    def event_generator():
        while True:
            item = q.get()
            yield f"data: {json.dumps(item)}\n\n"
            if item.get("type") in ("done", "error", "end"):
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/metrics")
def metrics():
    # return simple in-memory metrics
    return get_metrics()


@app.get("/api/cache")
def list_cache():
    settings = get_settings()
    cache_dir = Path(settings.github_cache_dir_value)
    items = []
    if cache_dir.exists():
        for p in sorted(cache_dir.glob("*.json")):
            try:
                items.append({
                    "key": p.name,
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                })
            except Exception:
                continue
    return {"cache_dir": str(cache_dir), "keys": items}


@app.post("/api/cache/clear")
def clear_cache():
    settings = get_settings()
    cache_dir = Path(settings.github_cache_dir_value)
    removed = 0
    if cache_dir.exists():
        for p in cache_dir.glob("*.json"):
            try:
                p.unlink()
                removed += 1
            except Exception:
                continue
    return {"removed": removed}


@app.post("/api/cache/clear/{key}")
def clear_cache_key(key: str):
    settings = get_settings()
    cache_dir = Path(settings.github_cache_dir_value)
    removed = 0
    target = cache_dir / key
    if target.exists() and target.is_file():
        try:
            target.unlink()
            removed = 1
        except Exception:
            removed = 0
    return {"removed": removed}
