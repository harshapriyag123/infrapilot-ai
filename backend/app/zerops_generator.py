import yaml


def _signal_names(analysis: dict) -> set[str]:
    return {s["name"] for s in analysis["signals"]}


def generate_zerops_yaml(analysis: dict) -> str:
    """Generate a conservative starter config for common detected stacks."""
    names = _signal_names(analysis)
    services = []

    for svc in analysis.get("services", []):
        stype = (svc.get("service_type") or "").lower()
        runtime = svc.get("runtime") or ""
        framework = svc.get("framework") or ""
        path = svc.get("path") or "."

        if stype == "web":
            if framework == "Next.js":
                services.append({
                    "setup": "frontend",
                    "build": {
                        "base": "nodejs@22",
                        "buildCommands": ["npm ci", "npm run build"],
                        "deployFiles": ["./"],
                    },
                    "run": {
                        "base": "nodejs@22",
                        "ports": [{"port": 3000, "httpSupport": True}],
                        "start": "npm start",
                    },
                })
            else:
                services.append({
                    "setup": "frontend",
                    "build": {
                        "base": "nodejs@22",
                        "buildCommands": ["npm ci", "npm run build"],
                        "deployFiles": ["dist"],
                    },
                    "run": {
                        "base": "static",
                        "ports": [{"port": 80, "httpSupport": True}],
                    },
                })
        elif stype == "api":
            if runtime == "Python":
                services.append({
                    "setup": "api",
                    "build": {
                        "base": "python@3.12",
                        "buildCommands": ["pip install --target vendor -r requirements.txt"],
                        "deployFiles": ["./", "vendor"],
                    },
                    "run": {
                        "base": "python@3.12",
                        "ports": [{"port": 8000, "httpSupport": True}],
                        "envVariables": {"PYTHONPATH": "/var/www/vendor"},
                        "start": "uvicorn main:app --host 0.0.0.0 --port 8000",
                    },
                })
            elif runtime == "Node.js":
                services.append({
                    "setup": "api",
                    "build": {
                        "base": "nodejs@22",
                        "buildCommands": ["npm ci", "npm run build --if-present"],
                        "deployFiles": ["./"],
                    },
                    "run": {
                        "base": "nodejs@22",
                        "ports": [{"port": 3000, "httpSupport": True}],
                        "start": "npm start",
                    },
                })
            else:
                services.append({
                    "setup": "api",
                    "build": {"base": "ubuntu@latest", "buildCommands": ["echo 'Review this service build'"], "deployFiles": ["./"]},
                    "run": {"base": "ubuntu@latest", "start": "echo 'Review this service start' && sleep infinity"},
                })
        elif stype == "worker":
            if runtime == "Python":
                services.append({
                    "setup": "worker",
                    "build": {
                        "base": "python@3.12",
                        "buildCommands": ["pip install --target vendor -r requirements.txt"],
                        "deployFiles": ["./", "vendor"],
                    },
                    "run": {
                        "base": "python@3.12",
                        "envVariables": {"PYTHONPATH": "/var/www/vendor"},
                        "start": svc.get("start_command") or "python worker.py",
                    },
                })
            else:
                services.append({
                    "setup": "worker",
                    "build": {"base": "ubuntu@latest", "buildCommands": ["echo 'Review this worker build'"], "deployFiles": ["./"]},
                    "run": {"base": "ubuntu@latest", "start": svc.get("start_command") or "echo 'Review this worker start' && sleep infinity"},
                })

    if not services:
        services.append({
            "setup": "app",
            "run": {"base": "ubuntu@latest", "start": "echo 'Customize this service start command' && sleep infinity"},
        })

    return yaml.safe_dump({"zerops": services}, sort_keys=False, width=1000)
