import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const defaultApiBase = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "" : "https://api-23d-8000.ny1.zerops.app");

const API = defaultApiBase.replace(/\/$/, "");

async function request(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
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
  const safeScore = Number.isFinite(Number(score)) ? Number(score) : 0;
  const angle = Math.round((safeScore / 100) * 360);

  return (
    <div
      className="score-ring"
      style={{ "--score-angle": `${angle}deg` }}
    >
      <div>
        <strong>{safeScore}</strong>
        <span>/100</span>
      </div>
    </div>
  );
}

function StatusPill({ children, kind = "neutral" }) {
  return <span className={`pill ${kind}`}>{children}</span>;
}

function Architecture({ architecture }) {
  if (!architecture?.nodes?.length) {
    return (
      <p className="micro">
        No high-confidence service relationships were inferred.
      </p>
    );
  }

  const nodeMap = Object.fromEntries(
    architecture.nodes.map((node) => [node.id, node])
  );

  return (
    <div className="arch">
      <div className="arch-nodes">
        {architecture.nodes.map((node) => (
          <div
            key={node.id}
            className={`arch-node node-${node.type || "runtime"}`}
          >
            <small>{(node.type || "runtime").toUpperCase()}</small>
            <strong>{node.label}</strong>
          </div>
        ))}
      </div>

      <div className="edge-list">
        {(architecture.edges || []).map((edge, index) => (
          <div key={`${edge.source}-${edge.target}-${index}`} className="edge">
            <span>{nodeMap[edge.source]?.label || edge.source}</span>
            <b>→</b>
            <span>{nodeMap[edge.target]?.label || edge.target}</span>
            {edge.label && <em>{edge.label}</em>}
          </div>
        ))}
      </div>
    </div>
  );
}

const readinessAdvice = {
  "Runtime detected": {
    success:
      "A supported runtime was inferred from dependency or configuration files.",
    failure:
      "InfraPilot could not infer a runtime. Ensure the repository contains a dependency manifest such as package.json, requirements.txt, or pyproject.toml.",
  },

  "Framework detected": {
    success:
      "The application framework was identified from dependencies or configuration.",
    failure:
      "No explicit framework was detected. Add framework-specific configuration or dependencies such as FastAPI, Django, Flask, Next.js, React, or similar.",
  },

  "Dependency manifest": {
    success:
      "A dependency manifest was found, which helps runtime and dependency analysis.",
    failure:
      "No dependency manifest was detected. Add package.json, requirements.txt, pyproject.toml, go.mod, pom.xml, Cargo.toml, or equivalent.",
  },

  "Deployment configuration": {
    success:
      "Existing deployment or container configuration was detected.",
    failure:
      "No deployment configuration was detected. Add Dockerfile, zerops.yaml, zerops.yml, or a Compose configuration.",
  },

  "Environment contract": {
    success:
      "Environment requirements are discoverable through configuration or sample files.",
    failure:
      "No environment contract was discovered. Add .env.example or document required environment variables.",
  },

  "Database/managed state": {
    success:
      "Stateful dependencies were detected and can be modeled explicitly.",
    failure:
      "No database or managed state was inferred. Add PostgreSQL, MongoDB, Redis, or equivalent configuration if persistence is required.",
  },

  "Health endpoint/check": {
    success:
      "A health endpoint or healthcheck was detected.",
    failure:
      "No health endpoint or healthcheck was found. Add /health or a similar endpoint for readiness and operational verification.",
  },

  "Tests detected": {
    success:
      "Automated test files were detected.",
    failure:
      "No test files were detected. Add at least a smoke or integration test for the deployment-critical path.",
  },
};

function renderCheckAdvice(check) {
  const advice = readinessAdvice[check.name];

  if (!advice) return null;

  return (
    <div className="check-advice">
      <p>{check.ok ? advice.success : advice.failure}</p>

      {!check.ok && (
        <p className="recommendation">
          <strong>Recommendation:</strong> {advice.failure}
        </p>
      )}
    </div>
  );
}

function App() {
  const [repoUrl, setRepoUrl] = useState(
    "https://github.com/tiangolo/full-stack-fastapi-template"
  );

  const [job, setJob] = useState(null);
  const [analysis, setAnalysis] = useState(null);

  const [error, setError] = useState("");

  const [logs, setLogs] = useState("");
  const [diagnosis, setDiagnosis] = useState("");
  const [diagnosing, setDiagnosing] = useState(false);

  const [streaming, setStreaming] = useState(false);
  const [progress, setProgress] = useState([]);

  const busy =
    streaming || (job && ["queued", "running"].includes(job.status));

  async function enqueueBackgroundJob() {
    const created = await request("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        repo_url: repoUrl.trim(),
      }),
    });

    setJob(created);
  }

  async function analyze() {
    const trimmedRepo = repoUrl.trim();

    if (!trimmedRepo) {
      setError("Enter a GitHub repository URL.");
      return;
    }

    if (!/^https?:\/\/github\.com\//i.test(trimmedRepo)) {
      setError(
        "InfraPilot currently accepts GitHub repository URLs such as https://github.com/owner/repository."
      );
      return;
    }

    setError("");
    setAnalysis(null);
    setJob(null);
    setProgress([]);
    setStreaming(true);

    const url =
      `${API}/api/analyze-stream?repo_url=` +
      encodeURIComponent(trimmedRepo);

    const es = new EventSource(url);

    let done = false;
    let fallbackStarted = false;

    const closeStream = () => {
      try {
        es.close();
      } catch { }
    };

    const fallbackToQueue = async () => {
      if (done || fallbackStarted) return;

      fallbackStarted = true;
      closeStream();
      setStreaming(false);

      try {
        await enqueueBackgroundJob();

        setError(
          "Live analysis is taking longer than expected. InfraPilot switched to background processing."
        );
      } catch (enqueueError) {
        setError(
          `Unable to start repository analysis: ${enqueueError.message}`
        );
      }
    };

    const timeout = setTimeout(fallbackToQueue, 8000);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === "progress") {
          setProgress((previous) => [
            ...previous,
            data.payload,
          ]);

          return;
        }

        if (data.type === "done") {
          done = true;
          clearTimeout(timeout);
          closeStream();
          setStreaming(false);
          setError("");
          setAnalysis(data.payload);

          return;
        }

        if (data.type === "error") {
          done = true;
          clearTimeout(timeout);
          closeStream();
          setStreaming(false);

          setError(
            typeof data.payload === "string"
              ? data.payload
              : "Repository analysis failed."
          );
        }
      } catch {
        // Ignore malformed SSE payloads.
      }
    };

    es.onerror = () => {
      fallbackToQueue();
    };
  }

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) {
      return;
    }

    let cancelled = false;
    let timer = null;

    async function poll(delay = 1500) {
      timer = setTimeout(async () => {
        if (cancelled) return;

        try {
          const next = await request(`/api/jobs/${job.id}`);

          if (cancelled) return;

          setJob(next);

          if (next.status === "completed" && next.analysis_id) {
            const result = await request(
              `/api/analyses/${next.analysis_id}`
            );

            if (!cancelled) {
              setAnalysis(result);
              setError("");
            }

            return;
          }

          if (next.status === "failed") {
            setError(
              next.error_hint ||
              next.error ||
              "Repository analysis failed."
            );

            return;
          }

          poll(1500);
        } catch (pollError) {
          setError(
            `Unable to retrieve analysis status: ${pollError.message}`
          );

          poll(Math.min(delay * 2, 15000));
        }
      }, delay);
    }

    poll();

    return () => {
      cancelled = true;

      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [job?.id, job?.status]);

  async function runDiagnosis() {
    const trimmedLogs = logs.trim();

    if (!trimmedLogs) {
      setDiagnosis(
        "Paste deployment logs before running Deployment Doctor."
      );
      return;
    }

    setDiagnosing(true);
    setDiagnosis("");

    try {
      const result = await request("/api/diagnose", {
        method: "POST",
        body: JSON.stringify({
          logs: trimmedLogs,
          context: analysis
            ? `${analysis.owner}/${analysis.repo}; stack=${(
              analysis.detected_stack || []
            )
              .map((signal) => signal.name)
              .join(", ")}`
            : "",
        }),
      });

      setDiagnosis(
        `[${result.provider || "analysis"}]\n\n${result.diagnosis}`
      );
    } catch (diagnosisError) {
      setDiagnosis(
        `Diagnosis failed: ${diagnosisError.message}`
      );
    } finally {
      setDiagnosing(false);
    }
  }

  async function copyGeneratedYaml() {
    try {
      await navigator.clipboard.writeText(
        analysis?.generated_zerops_yaml || ""
      );
    } catch {
      setError(
        "Unable to copy YAML automatically. Select the generated configuration manually."
      );
    }
  }

  return (
    <>
      <header>
        <a className="brand" href="#">
          <span className="brand-mark">IP</span>

          <span>
            InfraPilot <b>AI</b>
          </span>
        </a>

        <nav>
          <a href="#analyze">Analyze</a>
          <a href="#doctor">Deployment Doctor</a>

          <a
            href={`${API}/docs`}
            target="_blank"
            rel="noreferrer"
          >
            API Docs ↗
          </a>
        </nav>
      </header>

      <main>
        <section className="hero">
          <StatusPill kind="green">
            ZEROPS CHALLENGE · 2026
          </StatusPill>

          <h1>
            Your AI <span>Forward Deployment Engineer.</span>
          </h1>

          <p>
            Give InfraPilot a GitHub repository. It discovers
            the application architecture, identifies deployment
            requirements, generates an explainable Zerops plan,
            detects operational risks, and helps move the
            application toward verified production.
          </p>

          <div className="hero-chips">
            <StatusPill>Repository Intelligence</StatusPill>
            <StatusPill>Service Discovery</StatusPill>
            <StatusPill>Architecture Inference</StatusPill>
            <StatusPill>Zerops Planning</StatusPill>
            <StatusPill>Deployment Diagnosis</StatusPill>
          </div>
        </section>

        <section
          className="panel analyze-panel"
          id="analyze"
        >
          <div className="panel-title">
            <div>
              <span className="eyebrow">
                01 / REPOSITORY INTELLIGENCE
              </span>

              <h2>Analyze a GitHub repository</h2>
            </div>

            {job && (
              <StatusPill
                kind={
                  job.status === "completed"
                    ? "green"
                    : job.status === "failed"
                      ? "red"
                      : "amber"
                }
              >
                {job.status}
              </StatusPill>
            )}
          </div>

          <div className="repo-form">
            <input
              value={repoUrl}
              onChange={(event) =>
                setRepoUrl(event.target.value)
              }
              placeholder="https://github.com/owner/repository"
            />

            <button
              onClick={analyze}
              disabled={busy}
            >
              {busy
                ? "Analyzing…"
                : "Analyze repository →"}
            </button>
          </div>

          <p className="micro">
            Public GitHub repositories work without credentials.
            Configure GITHUB_TOKEN on the backend for higher
            GitHub API limits.
          </p>

          {streaming && (
            <div style={{ marginTop: 8 }}>
              <div className="spinner">
                Analyzing repository…
              </div>

              <div className="progress-list">
                {progress.map((item, index) => (
                  <div
                    key={`${index}-${JSON.stringify(item)}`}
                    className="progress-item"
                  >
                    {item?.stage ||
                      item?.event ||
                      item?.message ||
                      JSON.stringify(item)}
                  </div>
                ))}
              </div>
            </div>
          )}

          {error && (
            <div className="error">
              {error}
            </div>
          )}

          {job?.status === "failed" && (
            <div style={{ marginTop: 8 }}>
              <button
                className="secondary"
                onClick={analyze}
              >
                Retry analysis
              </button>
            </div>
          )}
        </section>

        {analysis && (
          <>
            <section className="summary-grid">
              <div className="panel score-card">
                <span className="eyebrow">
                  DEPLOYMENT READINESS
                </span>

                <ScoreRing
                  score={analysis.readiness_score}
                />

                <p>{analysis.summary}</p>
              </div>

              <div className="panel">
                <span className="eyebrow">
                  APPLICATION UNDERSTANDING
                </span>

                <h2>
                  {analysis.owner}/{analysis.repo}
                </h2>

                <div className="tag-grid">
                  {(analysis.detected_stack || []).map(
                    (signal, index) => (
                      <div
                        className="signal"
                        key={`${signal.name}-${index}`}
                      >
                        <b>{signal.name}</b>

                        <span>
                          {signal.category}
                        </span>

                        <small>
                          {signal.confidence}% ·{" "}
                          {signal.evidence}
                        </small>
                      </div>
                    )
                  )}
                </div>
              </div>
            </section>

            <section className="panel">
              <span className="eyebrow">
                02 / SERVICES
              </span>

              <h2>
                Discovered deployable services
              </h2>

              <div className="service-grid">
                {(analysis.services || []).map(
                  (service, index) => (
                    <div
                      className="service-card"
                      key={`${service.name || service.id}-${index}`}
                    >
                      <div className="service-header">
                        <div>
                          <strong>
                            {service.name ||
                              service.label ||
                              service.id}
                          </strong>

                          {service.path && (
                            <small>
                              {service.path}
                            </small>
                          )}
                        </div>

                        <StatusPill
                          kind={
                            service.service_type ===
                              "database" ||
                              service.service_type ===
                              "cache"
                              ? "amber"
                              : service.service_type ===
                                "worker"
                                ? "neutral"
                                : "green"
                          }
                        >
                          {(
                            service.service_type ||
                            service.type ||
                            "runtime"
                          ).toUpperCase()}
                        </StatusPill>
                      </div>

                      <div className="service-meta">
                        {service.runtime && (
                          <span>
                            {service.runtime}
                          </span>
                        )}

                        {service.framework && (
                          <span>
                            {service.framework}
                          </span>
                        )}

                        {service.confidence != null && (
                          <span>
                            {service.confidence}%
                            confidence
                          </span>
                        )}
                      </div>

                      <div className="service-evidence">
                        {Array.isArray(
                          service.evidence
                        ) ? (
                          service.evidence.map(
                            (evidence, evidenceIndex) => (
                              <small
                                key={evidenceIndex}
                              >
                                {typeof evidence ===
                                  "string"
                                  ? evidence
                                  : JSON.stringify(
                                    evidence
                                  )}
                              </small>
                            )
                          )
                        ) : (
                          <small>
                            {service.evidence ||
                              service.reason ||
                              "Evidence inferred from repository structure."}
                          </small>
                        )}
                      </div>
                    </div>
                  )
                )}
              </div>
            </section>

            <section className="panel">
              <span className="eyebrow">
                03 / ARCHITECTURE
              </span>

              <h2>
                Inferred service topology
              </h2>

              <Architecture
                architecture={analysis.architecture}
              />
            </section>

            <section className="two-col">
              <div className="panel">
                <span className="eyebrow">
                  READINESS CHECKS
                </span>

                <div className="check-list">
                  {(analysis.checks || []).map(
                    (check, index) => (
                      <div
                        className="check-item"
                        key={`${check.name}-${index}`}
                      >
                        <div className="check">
                          <span
                            className={
                              check.ok
                                ? "ok"
                                : "no"
                            }
                          >
                            {check.ok ? "✓" : "!"}
                          </span>

                          <div>
                            <b>{check.name}</b>
                            <small>
                              {check.detail}
                            </small>
                          </div>

                          <em>
                            +
                            {check.ok
                              ? check.points
                              : 0}
                            /{check.points}
                          </em>
                        </div>

                        {renderCheckAdvice(
                          check
                        )}
                      </div>
                    )
                  )}
                </div>
              </div>

              <div className="panel">
                <span className="eyebrow">
                  DEPLOYMENT RISKS
                </span>

                <div className="risk-list">
                  {!analysis.risks?.length && (
                    <p>
                      No deployment risks were
                      detected by the current
                      deterministic rules.
                    </p>
                  )}

                  {(analysis.risks || []).map(
                    (risk, index) => (
                      <div
                        className={`risk risk-${risk.severity}`}
                        key={`${risk.title}-${index}`}
                      >
                        <StatusPill
                          kind={
                            risk.severity ===
                              "high"
                              ? "red"
                              : risk.severity ===
                                "medium"
                                ? "amber"
                                : "neutral"
                          }
                        >
                          {risk.severity}
                        </StatusPill>

                        <b>{risk.title}</b>

                        <p>{risk.fix}</p>
                      </div>
                    )
                  )}
                </div>
              </div>
            </section>

            <section className="panel">
              <div className="panel-title">
                <div>
                  <span className="eyebrow">
                    04 / GENERATED DEPLOYMENT PLAN
                  </span>

                  <h2>
                    zerops.yaml starter
                  </h2>
                </div>

                <button
                  className="secondary"
                  onClick={copyGeneratedYaml}
                >
                  Copy YAML
                </button>
              </div>

              <pre className="code">
                {analysis.generated_zerops_yaml}
              </pre>

              <p className="micro">
                InfraPilot generates an evidence-based
                deployment starting point. Review
                repository-specific build paths,
                commands, ports, and environment
                mappings before deployment.
              </p>

              <p className="micro">
                This starter YAML includes secret
                mappings such as `GITHUB_TOKEN`.
                Set the value in Zerops as a protected
                environment secret, not in source code.
              </p>
            </section>

            <section className="panel">
              <span className="eyebrow">
                ENVIRONMENT CONTRACT
              </span>

              <h2>
                Detected environment variables
              </h2>

              <div className="env-list">
                {analysis.env_vars?.length ? (
                  analysis.env_vars.map(
                    (variable, index) => {
                      const isObject =
                        typeof variable ===
                        "object" &&
                        variable !== null;

                      const name = isObject
                        ? variable.name
                        : variable;

                      return (
                        <div
                          className="env-item"
                          key={`${name}-${index}`}
                        >
                          <div>
                            <strong>
                              {name}
                            </strong>

                            {isObject &&
                              variable.category && (
                                <span>
                                  {
                                    variable.category
                                  }
                                </span>
                              )}

                            {isObject &&
                              variable.source && (
                                <span>
                                  {
                                    variable.source
                                  }
                                </span>
                              )}
                          </div>

                          {isObject &&
                            Array.isArray(
                              variable.evidence
                            ) && (
                              <small>
                                {variable.evidence.join(
                                  " · "
                                )}
                              </small>
                            )}
                        </div>
                      );
                    }
                  )
                ) : (
                  <p>
                    No high-confidence environment
                    variables were found in the sampled
                    configuration files.
                  </p>
                )}
              </div>
            </section>
          </>
        )}

        <section
          className="panel doctor"
          id="doctor"
        >
          <span className="eyebrow">
            05 / AI DEPLOYMENT DOCTOR
          </span>

          <h2>
            Turn noisy deployment logs into an
            actionable recovery plan
          </h2>

          <div className="doctor-grid">
            <div>
              <label>
                Deployment log
              </label>

              <textarea
                value={logs}
                onChange={(event) =>
                  setLogs(event.target.value)
                }
                placeholder="Paste Zerops runtime or deployment logs here..."
              />

              <button
                onClick={runDiagnosis}
                disabled={diagnosing}
              >
                {diagnosing
                  ? "Diagnosing…"
                  : "Diagnose failure →"}
              </button>
            </div>

            <div>
              <label>
                InfraPilot diagnosis
              </label>

              <pre className="diagnosis">
                {diagnosis ||
                  "Paste a deployment error and InfraPilot will identify likely root causes, evidence, remediation steps, and verification guidance."}
              </pre>
            </div>
          </div>
        </section>

        <section className="final-cta">
          <span className="eyebrow">
            FROM REPOSITORY → VERIFIED PRODUCTION
          </span>

          <h2>
            Deployment should be explainable.
          </h2>

          <p>
            InfraPilot combines deterministic
            engineering signals with optional AI
            reasoning so developers can understand
            the architecture, deployment decisions,
            risks, and recovery path behind a
            production system.
          </p>
        </section>
      </main>

      <footer>
        <span>
          InfraPilot AI · Zerops Challenge 2026
        </span>

        <span>
          React · FastAPI · PostgreSQL · Python Worker
        </span>
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")).render(
  <App />
);