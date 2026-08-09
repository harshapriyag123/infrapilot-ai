from sqlalchemy.orm import Session

from .analyzer import detect
from .github_client import GitHubClient
from .models import Analysis, AnalysisJob
from .zerops_generator import generate_zerops_yaml


def analyze_job(db: Session, job: AnalysisJob) -> Analysis:
    snapshot = GitHubClient().snapshot(job.repo_url)
    result = detect(snapshot)
    generated_yaml = generate_zerops_yaml(result)

    stack_names = [s["name"] for s in result["signals"]]
    summary = (
        f"Detected {', '.join(stack_names[:6]) or 'an application runtime'} across "
        f"{len(snapshot.files)} repository files. InfraPilot inferred "
        f"{len(result['services'])} deployable service(s) and calculated a "
        f"{result['readiness_score']}/100 readiness score."
    )

    analysis = Analysis(
        job_id=job.id,
        owner=snapshot.owner,
        repo=snapshot.repo,
        default_branch=snapshot.default_branch,
        description=snapshot.description,
        detected_stack=result["signals"],
        services=result["services"],
        env_vars=result["env_vars"],
        risks=result["risks"],
        checks=result["checks"],
        architecture=result["architecture"],
        readiness_score=result["readiness_score"],
        generated_zerops_yaml=generated_yaml,
        summary=summary,
        file_count=len(snapshot.files),
    )
    db.add(analysis)
    db.flush()
    return analysis
