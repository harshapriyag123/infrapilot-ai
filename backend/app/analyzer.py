import json
import re
from dataclasses import dataclass, asdict
from pathlib import PurePosixPath

import yaml

from .github_client import RepoSnapshot


@dataclass
class Signal:
    name: str
    category: str
    confidence: int
    evidence: str


SERVICE_MANIFESTS = {
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Cargo.toml",
    "Gemfile",
}

ENTRYPOINTS = {
    "manage.py",
    "main.py",
    "app.py",
    "server.py",
    "index.js",
    "index.ts",
}

COMPOSE_FILES = {"docker-compose.yml", "docker-compose.yaml"}
ENV_FILES = {".env.example", ".env.sample", ".env.template", "example.env"}
EXTRA_CONFIG = {
    "vite.config.js",
    "vite.config.ts",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "nuxt.config.ts",
    "angular.json",
}
IMPORTANT_DIRS = (
    "apps/",
    "api/",
    "backend/",
    "frontend/",
    "services/",
    "packages/",
    "workers/",
    "server/",
    "client/",
    "web/",
)

ENV_RE = re.compile(r"(?:os\.getenv|os\.environ\.get|process\.env\.|import\.meta\.env\.)([A-Z][A-Z0-9_]{2,})")
ENV_ASSIGN_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*=", re.MULTILINE)


def _basename(path: str) -> str:
    return PurePosixPath(path).name


def _parent(path: str) -> str:
    parent = PurePosixPath(path).parent
    return str(parent) if parent != PurePosixPath('.') else ''


def _path_depth(path: str) -> int:
    return len(PurePosixPath(path).parts)


def has_file(snapshot: RepoSnapshot, name: str) -> bool:
    return any(_basename(p) == name for p in snapshot.files)


def content_for_name(snapshot: RepoSnapshot, name: str) -> str:
    parts = [v for p, v in snapshot.contents.items() if _basename(p) == name]
    return "\n".join(parts)


def add_signal(signals, name, category, confidence, evidence):
    if not any(s.name == name and s.category == category for s in signals):
        signals.append(Signal(name, category, confidence, evidence))


def _load_json(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _load_yaml(text: str) -> dict | None:
    if not text:
        return None
    try:
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _find_paths(snapshot: RepoSnapshot, name: str) -> list[str]:
    return [p for p in snapshot.files if _basename(p) == name]


def _collect_candidate_dirs(snapshot: RepoSnapshot) -> set[str]:
    dirs = set()
    for path in snapshot.files:
        name = _basename(path)
        if name in SERVICE_MANIFESTS or name in ENTRYPOINTS or name in COMPOSE_FILES or name in EXTRA_CONFIG:
            dirs.add(_parent(path))
        if name in ENTRYPOINTS and (any(path.startswith(prefix) for prefix in IMPORTANT_DIRS) or _path_depth(path) <= 4):
            dirs.add(_parent(path))
    if not dirs:
        dirs.add("")
    return dirs


def _parse_docker_compose(snapshot: RepoSnapshot) -> dict[str, dict]:
    services = {}
    for path in _find_paths(snapshot, "docker-compose.yml") + _find_paths(snapshot, "docker-compose.yaml"):
        content = snapshot.contents.get(path, "")
        compose = _load_yaml(content)
        if not compose:
            continue
        raw_services = compose.get("services") or compose.get("service")
        if not isinstance(raw_services, dict):
            continue
        for service_name, service_data in raw_services.items():
            if not isinstance(service_data, dict):
                continue
            services[service_name] = {
                "name": service_name,
                "build": service_data.get("build"),
                "image": service_data.get("image"),
                "command": service_data.get("command"),
                "ports": service_data.get("ports", []),
                "environment": service_data.get("environment", {}),
                "env_file": service_data.get("env_file", []),
                "depends_on": service_data.get("depends_on", []),
                "volumes": service_data.get("volumes", []),
                "healthcheck": service_data.get("healthcheck"),
                "labels": service_data.get("labels", {}),
                "raw": service_data,
                "evidence": f"{path} -> service {service_name}",
            }
    return services


def _parse_env_contract(snapshot: RepoSnapshot) -> list[dict]:
    env_vars: dict[str, dict] = {}
    for path, content in snapshot.contents.items():
        base = _basename(path)
        if base in ENV_FILES:
            for name in ENV_ASSIGN_RE.findall(content):
                info = env_vars.setdefault(name, {"evidence": [], "source": "contract"})
                if path not in info["evidence"]:
                    info["evidence"].append(path)
        for name in ENV_RE.findall(content):
            info = env_vars.setdefault(name, {"evidence": [], "source": "usage"})
            if path not in info["evidence"]:
                info["evidence"].append(path)
    result = []
    for name, info in sorted(env_vars.items()):
        category = "secret" if name.endswith("_KEY") or name.endswith("_SECRET") or name in {"DATABASE_URL", "REDIS_URL"} else "infra"
        result.append({
            "name": name,
            "required": True,
            "category": category,
            "evidence": info["evidence"],
            "source": info["source"],
        })
    return result


def _service_from_dir(snapshot: RepoSnapshot, path: str, compose_services: dict[str, dict], signals: dict[str, Signal]) -> dict | None:
    search_prefix = f"{path}/" if path else ""
    files_in_dir = [p for p in snapshot.files if p == path or p.startswith(search_prefix)]
    if not files_in_dir:
        return None
    file_names = {_basename(p) for p in files_in_dir}
    contents = "\n".join(snapshot.contents.get(p, "") for p in files_in_dir)
    lower_contents = contents.lower()
    service = {
        "id": path.replace("/", "_") or "root",
        "name": _basename(path) or "root",
        "path": path or ".",
        "service_type": "app",
        "framework": None,
        "runtime": None,
        "build_tool": None,
        "start_command": None,
        "build_command": None,
        "output_directory": None,
        "public": False,
        "dependencies": [],
        "evidence": [],
        "confidence": 60,
    }

    def add_evidence(value: str):
        if value not in service["evidence"]:
            service["evidence"].append(value)

    package_text = snapshot.contents.get(f"{search_prefix}package.json", "")
    if package_text:
        package_json = _load_json(package_text)
        package_text = json.dumps(package_json or {}).lower() if package_json else package_text.lower()
        service["dependencies"].append("package.json")

    requirements_text = snapshot.contents.get(f"{search_prefix}requirements.txt", "")
    pyproject_text = snapshot.contents.get(f"{search_prefix}pyproject.toml", "")
    pipfile_text = snapshot.contents.get(f"{search_prefix}Pipfile", "")
    manifest_text = "\n".join([requirements_text, pyproject_text, pipfile_text]).lower()

    if package_text:
        service["runtime"] = "Node.js"
        if "react" in package_text:
            service["framework"] = "React"
            service["service_type"] = "web"
            service["build_tool"] = "Vite"
            service["output_directory"] = "dist"
            service["build_command"] = "npm ci && npm run build"
            service["start_command"] = "npm run preview"
            service["public"] = True
            add_evidence(f"{path}/package.json")
        if "next" in package_text:
            service["framework"] = "Next.js"
            service["service_type"] = "web"
            service["build_tool"] = "Next.js"
            service["output_directory"] = ".next"
            service["build_command"] = "npm ci && npm run build"
            service["start_command"] = "npm start"
            service["public"] = True
            add_evidence(f"{path}/package.json")
        if "vite" in package_text and service["framework"] is None:
            service["framework"] = "Vite"
            service["service_type"] = "web"
            service["build_tool"] = "Vite"
            service["output_directory"] = "dist"
            service["build_command"] = "npm ci && npm run build"
            service["start_command"] = "npm run preview"
            service["public"] = True
            add_evidence(f"{path}/package.json")
        if "express" in package_text and service["framework"] is None:
            service["framework"] = "Express"
            service["service_type"] = "api"
            service["build_tool"] = "npm"
            service["build_command"] = "npm ci"
            service["start_command"] = "npm start"
            service["public"] = True
            add_evidence(f"{path}/package.json")
        if "@nestjs" in package_text:
            service["framework"] = "NestJS"
            service["service_type"] = "api"
            service["build_tool"] = "npm"
            service["build_command"] = "npm ci && npm run build"
            service["start_command"] = "npm run start"
            service["public"] = True
            add_evidence(f"{path}/package.json")

    if manifest_text:
        service["runtime"] = service["runtime"] or "Python"
        service["build_tool"] = service["build_tool"] or "pip"
        service["build_command"] = service["build_command"] or "pip install -r requirements.txt"
        service["output_directory"] = service["output_directory"] or "."
        service["public"] = True
        if "fastapi" in manifest_text or "from fastapi" in lower_contents:
            service["framework"] = "FastAPI"
            service["service_type"] = "api"
            service["start_command"] = service["start_command"] or "uvicorn main:app --host 0.0.0.0 --port 8000"
            add_evidence(f"{path}/requirements.txt")
        elif "django" in manifest_text or "manage.py" in file_names or "settings.py" in file_names:
            service["framework"] = "Django"
            service["service_type"] = "api"
            service["start_command"] = service["start_command"] or "python manage.py runserver 0.0.0.0:8000"
            add_evidence(f"{path}/manage.py")
        elif "flask" in manifest_text or "from flask" in lower_contents:
            service["framework"] = "Flask"
            service["service_type"] = "api"
            service["start_command"] = service["start_command"] or "python app.py"
            add_evidence(f"{path}/requirements.txt")
        elif "celery" in manifest_text or "rq" in manifest_text or "celery" in lower_contents:
            service["framework"] = "Celery"
            service["service_type"] = "worker"
            service["public"] = False
            service["start_command"] = service["start_command"] or "celery -A app worker --loglevel=info"
            add_evidence(f"{path}/requirements.txt")

    if "requirements.txt" in file_names or "pyproject.toml" in file_names or "Pipfile" in file_names:
        service["dependencies"].append("requirements.txt" if "requirements.txt" in file_names else "pyproject.toml")

    if "Dockerfile" in file_names:
        service["confidence"] = max(service["confidence"], 70)
        add_evidence(f"{path}/Dockerfile")

    if service["runtime"] is None and any(name in file_names for name in {"main.py", "app.py", "server.py"}):
        service["runtime"] = "Python"
        service["framework"] = service["framework"] or "Python"
        service["service_type"] = service["service_type"] or "api"
        service["public"] = True
        add_evidence(f"{path}/main.py")

    compose_match = None
    for compose in compose_services.values():
        build = compose.get("build")
        image = str(compose.get("image", ""))
        if isinstance(build, str) and build.strip("./") == path:
            compose_match = compose
        elif isinstance(build, dict) and str(build.get("context", "")).strip("./") == path:
            compose_match = compose
        elif path and compose["name"].lower() == _basename(path).lower():
            compose_match = compose
        if compose_match:
            add_evidence(compose_match["evidence"])
            if compose_match.get("ports"):
                service["public"] = True
            if compose_match.get("command") and not service["start_command"]:
                service["start_command"] = compose_match.get("command")
            env = compose_match.get("environment")
            if isinstance(env, dict):
                for key in env.keys():
                    add_evidence(f"{compose_match['evidence']} -> {key}")
            elif isinstance(env, list):
                for entry in env:
                    if isinstance(entry, str) and "=" in entry:
                        add_evidence(f"{compose_match['evidence']} -> {entry.split('=',1)[0]}")
            break

    if service["service_type"] == "app" and service["runtime"] == "Node.js":
        service["service_type"] = "web"
    if service["service_type"] == "app" and service["runtime"] == "Python":
        service["service_type"] = "api"
    if service["service_type"] == "app" and path.lower().startswith("frontend"):
        service["service_type"] = "web"
        service["public"] = True
    if service["service_type"] == "app" and path.lower().startswith("backend"):
        service["service_type"] = "api"

    service["label"] = PurePosixPath(service["path"]).name if service["path"] and service["path"] != "." else "root"

    if not service["framework"] and service["runtime"] == "Python":
        service["framework"] = "Python"
    if not service["framework"] and service["runtime"] == "Node.js":
        service["framework"] = "Node.js"
    if service["runtime"] is None and service["framework"] is None and service["evidence"]:
        service["runtime"] = "Unknown"

    return service


def detect(snapshot: RepoSnapshot) -> dict:
    signals: list[Signal] = []
    file_names = {PurePosixPath(p).name for p in snapshot.files}
    all_text = "\n".join(snapshot.contents.values())
    package = content_for_name(snapshot, "package.json")
    requirements = content_for_name(snapshot, "requirements.txt")
    pyproject = content_for_name(snapshot, "pyproject.toml")
    docker_compose = content_for_name(snapshot, "docker-compose.yml") + content_for_name(snapshot, "docker-compose.yaml")

    def has_file_name(name: str) -> bool:
        return name in file_names

    if has_file_name("package.json"):
        add_signal(signals, "Node.js", "runtime", 98, "package.json")
    if has_file_name("requirements.txt") or has_file_name("pyproject.toml"):
        add_signal(signals, "Python", "runtime", 98, "requirements.txt/pyproject.toml")
    if has_file(snapshot, "go.mod"):
        add_signal(signals, "Go", "runtime", 98, "go.mod")
    if has_file(snapshot, "Cargo.toml"):
        add_signal(signals, "Rust", "runtime", 98, "Cargo.toml")
    if has_file(snapshot, "pom.xml") or has_file(snapshot, "build.gradle") or has_file(snapshot, "build.gradle.kts"):
        add_signal(signals, "Java", "runtime", 95, "Maven/Gradle config")

    lower_package = package.lower()
    lower_py = (requirements + "\n" + pyproject + "\n" + all_text[:300_000]).lower()
    if '"react"' in lower_package or "'react'" in lower_package:
        add_signal(signals, "React", "framework", 96, "React dependency")
    if '"vite"' in lower_package or has_file_name("vite.config.ts") or has_file_name("vite.config.js"):
        add_signal(signals, "Vite", "build-tool", 96, "Vite config/dependency")
    if '"next"' in lower_package or any(name.startswith("next.config") for name in file_names):
        add_signal(signals, "Next.js", "framework", 98, "Next.js config/dependency")
    if "fastapi" in lower_py:
        add_signal(signals, "FastAPI", "framework", 96, "FastAPI import/dependency")
    if "django" in lower_py or has_file_name("manage.py"):
        add_signal(signals, "Django", "framework", 96, "Django dependency/manage.py")
    if "flask" in lower_py:
        add_signal(signals, "Flask", "framework", 92, "Flask import/dependency")
    if "@nestjs" in lower_package:
        add_signal(signals, "NestJS", "framework", 96, "NestJS dependency")
    if has_file_name("angular.json"):
        add_signal(signals, "Angular", "framework", 98, "angular.json")

    if "postgres" in lower_py or "postgres" in lower_package or "postgres" in docker_compose.lower() or "psycopg" in lower_py:
        add_signal(signals, "PostgreSQL", "database", 90, "PostgreSQL client/config detected")
    if "mongodb" in lower_package or "mongoose" in lower_package or "pymongo" in lower_py:
        add_signal(signals, "MongoDB", "database", 88, "MongoDB client detected")
    if "redis" in lower_py or "redis" in lower_package or "valkey" in all_text.lower():
        add_signal(signals, "Redis/Valkey", "cache", 85, "Redis/Valkey dependency detected")
    if "celery" in lower_py or "rq" in lower_py:
        add_signal(signals, "Background Worker", "worker", 92, "Celery/RQ detected")
    if has_file(snapshot, "Dockerfile"):
        add_signal(signals, "Docker", "container", 92, "Dockerfile")
    if has_file(snapshot, "docker-compose.yml") or has_file(snapshot, "docker-compose.yaml"):
        add_signal(signals, "Docker Compose", "orchestration", 95, "docker-compose")

    env_contract = _parse_env_contract(snapshot)
    env_vars = [item["name"] for item in env_contract]

    compose_services = _parse_docker_compose(snapshot)
    candidate_dirs = _collect_candidate_dirs(snapshot)

    services = []
    seen_paths = set()
    for path in sorted(candidate_dirs, key=lambda p: _path_depth(p)):
        if path in seen_paths:
            continue
        service = _service_from_dir(snapshot, path, compose_services, {s.name: s for s in signals})
        if service is None:
            continue
        if service["path"] in seen_paths:
            continue
        seen_paths.add(service["path"])
        services.append(service)

    compose_names = {s["name"] for s in services}
    for compose_name, compose in compose_services.items():
        if compose_name in compose_names:
            continue
        image = str(compose.get("image", "")).lower()
        if "postgres" in image:
            services.append({
                "id": f"db_{compose_name}",
                "name": compose_name,
                "path": "",
                "service_type": "database",
                "framework": "PostgreSQL",
                "runtime": "PostgreSQL",
                "build_tool": None,
                "start_command": None,
                "build_command": None,
                "output_directory": None,
                "public": False,
                "dependencies": ["docker-compose"],
                "evidence": [compose["evidence"]],
                "confidence": 92,
            })
        elif "redis" in image:
            services.append({
                "id": f"cache_{compose_name}",
                "name": compose_name,
                "path": "",
                "service_type": "cache",
                "framework": "Redis",
                "runtime": "Redis",
                "build_tool": None,
                "start_command": None,
                "build_command": None,
                "output_directory": None,
                "public": False,
                "dependencies": ["docker-compose"],
                "evidence": [compose["evidence"]],
                "confidence": 90,
            })

    if not services:
        services.append({
            "id": "app",
            "name": "Application",
            "path": ".",
            "service_type": "runtime",
            "framework": None,
            "runtime": None,
            "build_tool": None,
            "start_command": None,
            "build_command": None,
            "output_directory": None,
            "public": False,
            "dependencies": [],
            "evidence": ["Fallback single service"],
            "confidence": 50,
        })

    checks = []
    score = 0

    def check(name, ok, points, detail):
        nonlocal score
        if ok:
            score += points
        checks.append({"name": name, "ok": bool(ok), "points": points, "detail": detail})

    check("Runtime detected", any(s.category == "runtime" for s in signals), 15, "A supported application runtime was inferred.")
    check("Framework detected", any(s.category == "framework" for s in signals), 15, "Application framework was identified.")
    check("Dependency manifest", any(has_file(snapshot, x) for x in ["package.json", "requirements.txt", "pyproject.toml", "go.mod", "pom.xml", "Cargo.toml"]), 15, "Dependency manifest is present.")
    check("Deployment configuration", has_file(snapshot, "zerops.yaml") or has_file(snapshot, "zerops.yml") or has_file(snapshot, "Dockerfile"), 15, "Existing deployment/container configuration found.")
    check("Environment contract", bool(env_contract) or any(_basename(p) in ENV_FILES for p in snapshot.files), 10, "Environment variables are discoverable.")
    check("Database/managed state", any(s["service_type"] == "database" for s in services), 10, "Stateful dependency can be modeled explicitly.")
    health = any("/health" in text or "healthcheck" in text.lower() for text in snapshot.contents.values())
    check("Health endpoint/check", health, 10, "Health endpoint or healthcheck configuration detected.")
    testish = any(("test" in PurePosixPath(p).name.lower() or "/tests/" in f"/{p.lower()}/") for p in snapshot.files)
    check("Tests detected", testish, 10, "Automated test files are present.")

    risks = []
    if not health:
        risks.append({"severity": "medium", "title": "No health endpoint detected", "fix": "Add /health and verify critical dependencies."})
    if env_vars and not any(_basename(p) in ENV_FILES for p in snapshot.files):
        risks.append({"severity": "medium", "title": "Environment variables detected without an example contract", "fix": "Add .env.example with names only, never secrets."})
    if not has_file(snapshot, "zerops.yaml") and not has_file(snapshot, "zerops.yml"):
        risks.append({"severity": "high", "title": "No Zerops deployment configuration", "fix": "Use InfraPilot's generated zerops.yaml as a starting point."})
    if not testish:
        risks.append({"severity": "low", "title": "No tests detected", "fix": "Add at least a smoke test for the deployment-critical path."})
    if len(snapshot.files) >= 5000:
        risks.append({"severity": "low", "title": "Large repository", "fix": "Analysis sampled the first 5,000 files. Consider scoped analysis."})

    architecture = build_architecture(services)

    return {
        "signals": [asdict(s) for s in sorted(signals, key=lambda x: (-x.confidence, x.name))],
        "services": services,
        "env_vars": env_contract,
        "checks": checks,
        "readiness_score": min(score, 100),
        "risks": risks,
        "architecture": architecture,
    }


def build_architecture(services: list[dict]) -> dict:
    nodes = [{"id": s["id"], "label": s["label"], "type": s["service_type"]} for s in services]
    web_ids = [s["id"] for s in services if s["service_type"] == "web"]
    api_ids = [s["id"] for s in services if s["service_type"] == "api"]
    db_ids = [s["id"] for s in services if s["service_type"] == "database"]
    cache_ids = [s["id"] for s in services if s["service_type"] == "cache"]
    worker_ids = [s["id"] for s in services if s["service_type"] == "worker"]
    edges = []
    for frontend in web_ids:
        for api in api_ids:
            edges.append({"source": frontend, "target": api, "label": "HTTP"})
    for api in api_ids:
        for db in db_ids:
            edges.append({"source": api, "target": db, "label": "SQL/driver"})
        for cache in cache_ids:
            edges.append({"source": api, "target": cache, "label": "cache/queue"})
    for worker in worker_ids:
        for db in db_ids:
            edges.append({"source": worker, "target": db, "label": "jobs/state"})
        for cache in cache_ids:
            edges.append({"source": worker, "target": cache, "label": "queue"})
    return {"nodes": nodes, "edges": edges}
