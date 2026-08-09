from backend.app.analyzer import detect
from backend.app.github_client import RepoSnapshot


def test_detects_fastapi_react_postgres():
    snap = RepoSnapshot(
        owner="demo",
        repo="demo",
        default_branch="main",
        description=None,
        files=[
            "frontend/package.json",
            "backend/requirements.txt",
            "backend/main.py",
            "tests/test_api.py",
        ],
        contents={
            "frontend/package.json": '{"dependencies":{"react":"x","vite":"x"}}',
            "backend/requirements.txt": "fastapi\npsycopg[binary]\n",
            "backend/main.py": 'import os\nfrom fastapi import FastAPI\nDATABASE_URL=os.getenv("DATABASE_URL")\napp=FastAPI()\n@app.get("/health")\ndef health(): return {"ok":True}',
        },
    )
    result = detect(snap)
    names = {s["name"] for s in result["signals"]}
    assert {"React", "Vite", "Python", "FastAPI", "PostgreSQL"} <= names
    assert result["readiness_score"] > 50
