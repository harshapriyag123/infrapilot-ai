import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

@property
def cors_origin_list(self) -> list[str]:
origins = (
  self.cors_origins
        or "https://frontend-23d.ny1.zerops.app,http://localhost:5173"
    )
return [x.strip() for x in origins.split(",") if x.strip()]

async function request(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch { }
    throw new Error(detail);
  }
  return res.json();
}

function ScoreRing({ score }) {
  const angle = Math.round((score / 100) * 360);
  return (
    <div className="score-ring" style={{ "--score-angle": `${angle}deg` }}>
      <div>
        <strong>{score}</strong>
        <span>/100</span>
      </div>
    </div>
  );
}

function StatusPill({ children, kind = "neutral" }) {
  return <span className={`pill ${kind}`}>{children}</span>;
}

function Architecture({ architecture }) {
  if (!architecture?.nodes?.length) return null;
  const nodeMap = Object.fromEntries(architecture.nodes.map(n => [n.id, n]));
  return (
    <div className="arch">
      <div className="arch-nodes">
        {architecture.nodes.map((n) => (
          <div key={n.id} className={`arch-node node-${n.type}`}>
            <small>{n.type.toUpperCase()}</small>
            <strong>{n.label}</strong>
          </div>
        ))}
      </div>
      <div className="edge-list">
        {architecture.edges.map((e, i) => (
          <div key={i} className="edge">
            <span>{nodeMap[e.source]?.label || e.source}</span>
            <b>→</b>
            <span>{nodeMap[e.target]?.label || e.target}</span>
            <em>{e.label}</em>
          </div>
        ))}
      </div>
    </div>
  );
}

const readinessAdvice = {
  "Runtime detected": {
    success: "A supported runtime was inferred from dependency or config files.",
    failure: "InfraPilot could not infer a runtime. Ensure your repository includes a dependency manifest such as package.json, requirements.txt, or pyproject.toml."
  },
  "Framework detected": {
    success: "The application framework was identified from dependencies or config.",
    failure: "No explicit framework was detected. Add framework-specific config or dependencies (FastAPI, Django, Flask, Next.js, React, etc.) so the platform can infer the app type."
  },
  "Dependency manifest": {
    success: "A dependency manifest was found, which helps dependency and runtime analysis.",
    failure: "No dependency manifest was detected. Add package.json, requirements.txt, pyproject.toml, go.mod, pom.xml, or Cargo.toml so InfraPilot can identify your runtime and packages."
  },
  "Deployment configuration": {
    success: "Deployment/container configuration was found.",
    failure: "No deployment configuration was sampled. Add a Dockerfile, zerops.yaml, zerops.yml, or docker-compose file to describe how this app should be deployed."
  },
  "Environment contract": {
    success: "Environment variables are discoverable through config or sample files.",
    failure: "No environment contract was discovered. Add .env.example or document required environment variables in your config files."
  },
  "Database/managed state": {
    success: "Stateful dependencies were detected, which allows deployment to model storage needs.",
    failure: "No database or managed state was inferred. Add PostgreSQL, MongoDB, Redis, or other stateful service configuration if your app requires persistent storage."
  },
  "Health endpoint/check": {
    success: "A health endpoint or healthcheck was detected, which helps operational readiness.",
    failure: "No health endpoint or healthcheck could be found. Add /health or similar endpoints and document them so uptime and readiness can be validated."
  },
  "Tests detected": {
    success: "Automated test files were detected.",
    failure: "No test files were detected. Add a smoke test or integration tests to prove the deployment path."
  },
};

function renderCheckAdvice(check) {
  const advice = readinessAdvice[check.name];
  if (!advice) return null;
  return (
    <div className="check-advice">
      <p>{check.ok ? advice.success : advice.failure}</p>
      {!check.ok && <p className="recommendation"><strong>Recommendation:</strong> {advice.failure}</p>}
    </div>
  );
}

function App() {
  const [repoUrl, setRepoUrl] = useState("https://github.com/tiangolo/full-stack-fastapi-template");
  const [job, setJob] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [error, setError] = useState("");
  const [logs, setLogs] = useState("");
  const [diagnosis, setDiagnosis] = useState("");
  const [diagnosing, setDiagnosing] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [progress, setProgress] = useState([]);

  const busy = job && ["queued", "running"].includes(job.status);

  async function analyze() {
    setError("");
    setAnalysis(null);
    setJob(null);
    setProgress([]);
    setStreaming(true);

    const url = `${API}/api/analyze-stream?repo_url=${encodeURIComponent(repoUrl)}`;
    const es = new EventSource(url);
    let done = false;

    const timeoutMs = 8000;
    const timeout = setTimeout(async () => {
      if (!done) {
        try {
          es.close();
        } catch { }
        setStreaming(false);
        setError("Analysis is taking longer — queued for background processing.");
        try {
          const created = await request("/api/jobs", {
            method: "POST",
            body: JSON.stringify({ repo_url: repoUrl }),
          });
          setJob(created);
        } catch (e) {
          setError(prev => (prev ? prev + " " : "") + `Enqueue failed: ${e.message}`);
        }
      }
    }, timeoutMs);

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === "progress") {
          setProgress(prev => [...prev, data.payload]);
        } else if (data.type === "done") {
          done = true;
          clearTimeout(timeout);
          try { es.close(); } catch { }
          setStreaming(false);
          setAnalysis(data.payload);
        } else if (data.type === "error") {
          done = true;
          clearTimeout(timeout);
          try { es.close(); } catch { }
          setStreaming(false);
          setError(data.payload || "Analysis error");
        }
      } catch (err) {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      // ignore; fallback will trigger via timeout
    };
  }

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let cancelled = false;
    let delay = 1500;
    let consecutiveErrors = 0;

    async function poll() {
      if (cancelled) return;
      try {
        const next = await request(`/api/jobs/${job.id}`);
        if (cancelled) return;
        setJob(next);
        consecutiveErrors = 0;
        delay = 1500;
        if (next.status === "completed" && next.analysis_id) {
          const result = await request(`/api/analyses/${next.analysis_id}`);
          setAnalysis(result);
        }
        if (next.status === "failed") {
          // Prefer concise hints from the backend when available.
          setError(next.error_hint || next.error || "Analysis failed");
        }
      } catch (e) {
        consecutiveErrors += 1;
        delay = Math.min(1500 * 2 ** consecutiveErrors, 15000);
        setError(e.message);
      } finally {
        if (!cancelled && job && ["queued", "running"].includes(job.status)) {
          setTimeout(poll, delay);
        }
      }
    }

    poll();
    return () => {
      cancelled = true;
    };
  }, [job?.id, job?.status]);

  async function runDiagnosis() {
    setDiagnosing(true);
    setDiagnosis("");
    try {
      const result = await request("/api/diagnose", {
        method: "POST",
        body: JSON.stringify({
          logs,
          context: analysis ? `${analysis.owner}/${analysis.repo}; stack=${analysis.detected_stack.map(s => s.name).join(", ")}` : ""
        }),
      });
      setDiagnosis(`[${result.provider}]\n\n${result.diagnosis}`);
    } catch (e) {
      setDiagnosis(`Diagnosis failed: ${e.message}`);
    } finally {
      setDiagnosing(false);
    }
  }

  return (
    <>
      <header>
        <a className="brand" href="#"><span className="brand-mark">IP</span><span>InfraPilot <b>AI</b></span></a>
        <nav><a href="#analyze">Analyze</a><a href="#doctor">Deployment Doctor</a><a href={`${API}/docs`} target="_blank">API Docs ↗</a></nav>
      </header>

      <main>
        <section className="hero">
          <StatusPill kind="green">ZEROPS CHALLENGE · 2026</StatusPill>
          <h1>Your AI <span>Forward Deployment Engineer.</span></h1>
          <p>Turn an unfamiliar GitHub repository into an explainable deployment plan: stack detection, architecture, risk checks, readiness scoring, Zerops configuration, and failure diagnosis.</p>
          <div className="hero-chips">
            <StatusPill>Repository Intelligence</StatusPill>
            <StatusPill>Architecture Inference</StatusPill>
            <StatusPill>zerops.yaml</StatusPill>
            <StatusPill>Deployment Diagnosis</StatusPill>
          </div>
        </section>

        <section className="panel analyze-panel" id="analyze">
          <div className="panel-title">
            <div><span className="eyebrow">01 / REPOSITORY INTELLIGENCE</span><h2>Analyze a GitHub repository</h2></div>
            {job && <StatusPill kind={job.status === "completed" ? "green" : job.status === "failed" ? "red" : "amber"}>{job.status}</StatusPill>}
          </div>
          <div className="repo-form">
            <input value={repoUrl} onChange={e => setRepoUrl(e.target.value)} placeholder="https://github.com/owner/repository" />
            <button onClick={analyze} disabled={busy}>{busy ? "Analyzing…" : "Analyze repository →"}</button>
          </div>
          <p className="micro">Public GitHub repositories work without credentials. Add GITHUB_TOKEN on the backend for higher rate limits.</p>
          {streaming && (
            <div style={{ marginTop: 8 }}>
              <div className="spinner">Analyzing…</div>
              <div className="progress-list">
                {progress.map((p, i) => (
                  <div key={i} className="progress-item">{p.stage || p.event || JSON.stringify(p)}</div>
                ))}
              </div>
            </div>
          )}
          {error && <div className="error">{error}</div>}
          {job && job.status === "failed" && (
            <div style={{ marginTop: 8 }}>
              <button className="secondary" onClick={analyze}>Retry analysis</button>
            </div>
          )}
        </section>

        {analysis && (
          <>
            <section className="summary-grid">
              <div className="panel score-card">
                <span className="eyebrow">DEPLOYMENT READINESS</span>
                <ScoreRing score={analysis.readiness_score} />
                <p>{analysis.summary}</p>
              </div>
              <div className="panel">
                <span className="eyebrow">DETECTED STACK</span>
                <h2>{analysis.owner}/{analysis.repo}</h2>
                <div className="tag-grid">
                  {analysis.detected_stack.map((s, i) => (
                    <div className="signal" key={i}><b>{s.name}</b><span>{s.category}</span><small>{s.confidence}% · {s.evidence}</small></div>
                  ))}
                </div>
              </div>
            </section>

            <section className="panel">
              <span className="eyebrow">02 / SERVICES</span>
              <h2>Discovered deployable services</h2>
              <div className="service-grid">
                {analysis.services.map((s, i) => (
                  <div className="service-card" key={i}>
                    <div className="service-header">
                      <div>
                        <strong>{s.name}</strong>
                        <small>{s.path}</small>
                      </div>
                      <StatusPill kind={s.service_type === "database" ? "amber" : s.service_type === "cache" ? "amber" : s.service_type === "worker" ? "neutral" : "green"}>
                        {s.service_type?.toUpperCase()}
                      </StatusPill>
                    </div>
                    <div className="service-meta">
                      {s.runtime && <span>{s.runtime}</span>}
                      {s.framework && <span>{s.framework}</span>}
                      {s.confidence != null && <span>{s.confidence}% confidence</span>}
                    </div>
                    <div className="service-evidence">
                      {Array.isArray(s.evidence) ? s.evidence.map((e, j) => <small key={j}>{e}</small>) : <small>{s.evidence}</small>}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel">
              <span className="eyebrow">03 / ARCHITECTURE</span>
              <h2>Inferred service topology</h2>
              <Architecture architecture={analysis.architecture} />
            </section>

            <section className="two-col">
              <div className="panel">
                <span className="eyebrow">READINESS CHECKS</span>
                <div className="check-list">
                  {analysis.checks.map((c, i) => (
                    <div className="check-item" key={i}>
                      <div className="check">
                        <span className={c.ok ? "ok" : "no"}>{c.ok ? "✓" : "!"}</span>
                        <div><b>{c.name}</b><small>{c.detail}</small></div>
                        <em>+{c.ok ? c.points : 0}/{c.points}</em>
                      </div>
                      {renderCheckAdvice(c)}
                    </div>
                  ))}
                </div>
              </div>
              <div className="panel">
                <span className="eyebrow">RISKS</span>
                <div className="risk-list">
                  {analysis.risks.length === 0 && <p>No deployment risks detected by the MVP rules.</p>}
                  {analysis.risks.map((r, i) => (
                    <div className={`risk risk-${r.severity}`} key={i}>
                      <StatusPill kind={r.severity === "high" ? "red" : r.severity === "medium" ? "amber" : "neutral"}>{r.severity}</StatusPill>
                      <b>{r.title}</b>
                      <p>{r.fix}</p>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="panel">
              <div className="panel-title">
                <div><span className="eyebrow">03 / GENERATED DEPLOYMENT PLAN</span><h2>zerops.yaml starter</h2></div>
                <button className="secondary" onClick={() => navigator.clipboard.writeText(analysis.generated_zerops_yaml)}>Copy YAML</button>
              </div>
              <pre className="code">{analysis.generated_zerops_yaml}</pre>
              <p className="micro">Generated configurations are intentionally conservative starters. Review commands and paths against the repository before deploying.</p>
            </section>

            <section className="panel">
              <span className="eyebrow">ENVIRONMENT CONTRACT</span>
              <h2>Detected environment variables</h2>
              <div className="env-list">
                {analysis.env_vars.length ? analysis.env_vars.map((v, i) => (
                  <div className="env-item" key={v.name || i}>
                    <div>
                      <strong>{v.name ?? v}</strong>
                      {v.category && <span>{v.category}</span>}
                      {v.source && <span>{v.source}</span>}
                    </div>
                    {Array.isArray(v.evidence) && <small>{v.evidence.join(" · ")}</small>}
                  </div>
                )) : <p>No high-confidence environment variables found in sampled config files.</p>}
              </div>
            </section>
          </>
        )}

        <section className="panel doctor" id="doctor">
          <span className="eyebrow">04 / AI DEPLOYMENT DOCTOR</span>
          <h2>Turn noisy logs into an actionable recovery plan</h2>
          <div className="doctor-grid">
            <div>
              <label>Deployment log</label>
              <textarea value={logs} onChange={e => setLogs(e.target.value)} />
              <button onClick={runDiagnosis} disabled={diagnosing}>{diagnosing ? "Diagnosing…" : "Diagnose failure →"}</button>
            </div>
            <div>
              <label>InfraPilot diagnosis</label>
              <pre className="diagnosis">{diagnosis || "Paste a deployment error and InfraPilot will identify likely root causes, fixes, and verification steps."}</pre>
            </div>
          </div>
        </section>

        <section className="final-cta">
          <span className="eyebrow">FROM REPOSITORY → PRODUCTION READINESS</span>
          <h2>Deployment should be explainable.</h2>
          <p>InfraPilot combines deterministic engineering signals with optional AI reasoning so developers can understand the architecture and the decisions behind the deployment.</p>
        </section>
      </main>

      <footer>
        <span>InfraPilot AI · Zerops Challenge 2026</span>
        <span>React · FastAPI · PostgreSQL · Python Worker</span>
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
