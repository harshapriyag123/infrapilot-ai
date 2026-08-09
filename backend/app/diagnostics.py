import re
import httpx

from .config import get_settings


RULES = [
    (r"ModuleNotFoundError|No module named", "Python dependency is missing from the runtime environment. Verify requirements.txt/pyproject.toml and ensure dependencies are included in the deployed files or installed during the build."),
    (r"ECONNREFUSED|Connection refused", "A dependent service is unreachable. Verify the target hostname/port and ensure the service is running on the same Zerops private network."),
    (r"DATABASE_URL|password authentication failed|could not connect to server", "Database configuration is likely invalid or unavailable. Verify DATABASE_URL/credentials and the managed database service hostname."),
    (r"address already in use|EADDRINUSE", "The application is binding to a port that is already occupied. Ensure the process listens on the port declared in zerops.yaml."),
    (r"command not found|not found: command", "The runtime start command references a binary that is not available. Verify build outputs and runtime base technology."),
    (r"CORS|Access-Control-Allow-Origin", "The browser is blocking a cross-origin API request. Add the public frontend origin to backend CORS configuration."),
    (r"404|Not Found", "The request is reaching a server but the route or static asset path is incorrect. Verify public routing, base paths, and SPA fallback behavior."),
    (r"502|Bad Gateway", "The proxy cannot reach the application process. Check whether the process started, listens on 0.0.0.0, and uses the configured HTTP port."),
    (r"timeout|timed out", "A network call or startup step timed out. Inspect service reachability, external API latency, and startup work that may block readiness."),
]


def deterministic_diagnosis(logs: str) -> str:
    hits = []
    for pattern, explanation in RULES:
        if re.search(pattern, logs, flags=re.IGNORECASE):
            hits.append(explanation)
    if not hits:
        hits.append("No known signature matched. Start with the first error in chronological order, verify the start command and port, then check environment variables and dependent-service connectivity.")
    return (
        "Likely root cause\n\n"
        + "\n\n".join(f"- {h}" for h in hits[:4])
        + "\n\nRecommended recovery path\n\n"
          "1. Fix the earliest concrete error, not later cascading errors.\n"
          "2. Verify runtime command, bind address (0.0.0.0), and declared port.\n"
          "3. Verify required environment variables/secrets.\n"
          "4. Verify service-to-service hostnames and database connectivity.\n"
          "5. Redeploy and confirm the /health endpoint before testing the UI."
    )


def diagnose(logs: str, context: str = "") -> tuple[str, str]:
    settings = get_settings()
    if not settings.openai_api_key or not settings.openai_model:
        return "rules", deterministic_diagnosis(logs)

    prompt = f"""You are InfraPilot AI, a production deployment diagnostician.
Analyze the deployment log. Be concise and operational.
Return sections: Root cause, Evidence, Fix, Verification.
Do not invent facts not supported by the log/context.

Context:
{context}

Deployment log:
{logs}
"""
    try:
        with httpx.Client(timeout=40) as client:
            resp = client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "input": prompt,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            # Responses API convenience field is not guaranteed in raw JSON,
            # so collect output_text content items.
            pieces = []
            for item in data.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text" and content.get("text"):
                        pieces.append(content["text"])
            text = "\n".join(pieces).strip()
            if text:
                return "openai", text
    except Exception:
        pass

    return "rules-fallback", deterministic_diagnosis(logs)
