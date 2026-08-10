import logging
import time

from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.db import SessionLocal, init_db
from backend.app.models import AnalysisJob, ErrorLog
from backend.app.service import analyze_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("infrapilot-worker")


def claim_next_job(db):
    # Portable MVP queue. One worker is enough for the hackathon.
    job = db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.status == "queued")
        .order_by(AnalysisJob.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()

    if job:
        job.status = "running"
        job.error = None
        db.commit()
        db.refresh(job)
    return job


def run():
    init_db()
    settings = get_settings()
    log.info("InfraPilot worker started")

    while True:
        db = SessionLocal()
        try:
            job = claim_next_job(db)
            if not job:
                time.sleep(settings.worker_poll_seconds_value)
                continue

            log.info("Analyzing job=%s repo=%s", job.id, job.repo_url)
            try:
                analyze_job(db, job)
                job.status = "completed"
                db.commit()
                log.info("Completed job=%s", job.id)
            except Exception as exc:
                db.rollback()
                job = db.get(AnalysisJob, job.id)
                msg = str(exc)
                hint = None
                low = msg.lower()
                if "operationalerror" in low or "could not connect to server" in low or "connection refused" in low:
                    hint = "Database unreachable — verify DATABASE_URL and DB host"
                elif "unauthorized" in low or "401" in low or "403" in low or "forbidden" in low:
                    hint = "GitHub authentication failed — verify GITHUB_TOKEN/GITHUB_PAT/GH_TOKEN and restart the backend."
                elif "rate limit" in low or "rate limited" in low or "github api rate limit" in low:
                    hint = "GitHub rate limited — set GITHUB_TOKEN"

                if job:
                    job.status = "failed"
                    job.error = msg[:4000]
                    job.error_hint = hint
                    db.commit()
                    try:
                        log_rec = ErrorLog(job_id=job.id, message=msg[:4000], hint=hint)
                        db.add(log_rec)
                        db.commit()
                    except Exception:
                        db.rollback()
                log.exception("Job=%s failed: %s", job.id if job else "?", msg)
        finally:
            db.close()


if __name__ == "__main__":
    run()
