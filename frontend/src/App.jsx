
import { useState } from "react";
import "./App.css";

const API_URL = "http://localhost:8002";
const windowsBuildFields = [
  { key: "dotnet_project", label: ".NET Publish Project (optional)", placeholder: "src/Web/Web.csproj" },
  { key: "dotnet_framework", label: ".NET Target Framework (optional)", placeholder: "Detected from project" },
  { key: "dotnet_sdk_version", label: ".NET SDK Version (optional)", placeholder: "Detected from global.json / framework" },
  { key: "dotnet_runtime", label: "Windows Runtime", placeholder: "win-x64" },
  { key: "dotnet_self_contained", label: "Include .NET Runtime", type: "checkbox" },
  { key: "agent_name", label: "Deployment Agent Name (optional)", placeholder: "Agent on the destination server" },
];
const targetFields = {
  "linux-container": [
    { key: "container_port", label: "Container Port", placeholder: "8080", type: "number" },
    { key: "host_port", label: "Host Port", placeholder: "8082", type: "number" },
    { key: "health_check_url", label: "Health Check URL", placeholder: "http://localhost:8082/health" },
    { key: "build_platform", label: "Build Platform", placeholder: "linux/arm64 or linux/amd64" },
  ],
  iis: [
    ...windowsBuildFields,
    { key: "app_pool_name", label: "Application Pool", placeholder: "MyAppPool" },
    { key: "site_path", label: "Site Path", placeholder: "C:\\inetpub\\wwwroot\\MyApp" },
    { key: "health_check_url", label: "Health Check URL", placeholder: "http://localhost/health" },
  ],
  "windows-service": [
    ...windowsBuildFields,
    { key: "service_name", label: "Service Name", placeholder: "MyWorkerService" },
    { key: "install_path", label: "Install Path", placeholder: "C:\\Services\\MyWorker" },
    { key: "health_check_url", label: "Health Check URL (optional)", placeholder: "http://localhost/health" },
  ],
};

const initialForm = {
  repository_url: "",
  repository_name: "",
  project_name: "",
  default_branch: "main",
  deployment_target: "",
  agent_pool: "",
  container_port: "8080",
  host_port: "",
  build_platform: "",
  app_pool_name: "",
  site_path: "",
  health_check_url: "",
  service_name: "",
  install_path: "",
  dotnet_project: "",
  dotnet_framework: "",
  dotnet_sdk_version: "",
  dotnet_runtime: "",
  dotnet_self_contained: false,
  agent_name: "",
};

export default function App() {
  const [form, setForm] = useState(initialForm);
  const [yaml, setYaml] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const update = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setYaml("");
    setResult(null);
    setError("");
  };

  const payload = () => ({
    ...form,
    repository_name:
      form.repository_name.trim() ||
      form.repository_url.replace(/\/$/, "").split("/").pop()?.replace(/\.git$/, ""),
    agent_pool: form.agent_pool.trim() || null,
    host_port: form.deployment_target === "linux-container" && form.host_port ? Number(form.host_port) : null,
    build_platform: form.deployment_target === "linux-container" ? form.build_platform.trim() || null : null,
    container_port:
      form.deployment_target === "linux-container"
        ? Number(form.container_port)
        : null,
  });

  async function preview() {
    setLoading(true);
    setError("");
    setResult(null);
    setYaml("");

    try {
      const response = await fetch(`${API_URL}/api/pipeline/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail || data)
        );
      }

      setYaml(data.yaml || data.generated_yaml || "");
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function createPR() {
    if (!yaml || loading) return;

    if (!form.repository_url.startsWith("https://dev.azure.com/")) {
      setError("Pull Request için Azure Repos URL'si kullanmalısın.");
      return;
    }

    if (!form.project_name.trim()) {
      setError("Azure DevOps Project alanı zorunlu.");
      return;
    }

    if (!form.default_branch.trim()) {
      setError("Default Branch alanı zorunlu.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const requestData = {
        ...payload(),
        project_name: form.project_name.trim(),
        default_branch: form.default_branch.trim(),
        dry_run: true,
        confirmed: false,
      };

      // Önce değişiklik var mı kontrol et.
      const checkResponse = await fetch(`${API_URL}/api/pipeline/pr`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestData),
      });

      const checkData = await checkResponse.json();

      if (!checkResponse.ok) {
        throw new Error(
          typeof checkData.detail === "string"
            ? checkData.detail
            : JSON.stringify(checkData.detail || checkData)
        );
      }

      if (checkData.status === "SKIP") {
        setResult(checkData);
        return;
      }

      if (checkData.status !== "DRY_RUN") {
        throw new Error(`Beklenmeyen durum: ${checkData.status}`);
      }

      const confirmed = window.confirm(
        `Azure DevOps üzerinde ${checkData.decision} işlemi yapılacak.\n\n` +
        `Repository: ${form.repository_name || requestData.repository_name}\n` +
        `Project: ${form.project_name}\n` +
        `Target: ${form.default_branch}\n\n` +
        "Branch oluşturulabilir, commit gönderilebilir ve PR açılabilir.\n\n" +
        "Devam etmek istiyor musun?"
      );

      if (!confirmed) {
        setResult(checkData);
        return;
      }

      // Kullanıcı onayından sonra gerçek işlem.
      const response = await fetch(`${API_URL}/api/pipeline/pr`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...requestData,
          dry_run: false,
          confirmed: true,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail || data)
        );
      }

      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="logo">
          <span className="logo-icon">⚡</span>
          <span>AutoPipeline</span>
        </div>

        <div className="sidebar-label">WORKSPACE</div>
        <div className="nav-item active">▣ Pipeline Generator</div>
        <div className="nav-item">◇ Deployment Configuration</div>

        <div className="sidebar-bottom">
          <div className="status-dot" />
          <span>DevOps Automation Platform</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">AUTOMATION / PIPELINES</div>
            <h1>Pipeline Generator</h1>
            <p>Generate CI/CD pipelines for your deployment environment.</p>
          </div>
          <span className="version">v1.0 · Development</span>
        </header>

        <div className="content-grid">
          <section className="panel">
            <div className="panel-heading">
              <span className="step">01</span>
              <div>
                <h2>Repository Configuration</h2>
                <p>Connect your source code repository.</p>
              </div>
            </div>

            <label>Repository URL</label>
            <input
              value={form.repository_url}
              onChange={(e) => update("repository_url", e.target.value)}
              placeholder="https://github.com/username/repository"
            />

            <label>Repository Name</label>
            <input
              value={form.repository_name}
              onChange={(e) => update("repository_name", e.target.value)}
              placeholder="Optional — detected from URL"
            />
            <label>Azure DevOps Project</label>
            <input
              value={form.project_name}
              onChange={(e) => update("project_name", e.target.value)}
              placeholder="MultiStack-CICD"
            />

            <label>Default Branch</label>
            <input
              value={form.default_branch}
              onChange={(e) => update("default_branch", e.target.value)}
              placeholder="main"
            />

            <div className="separator" />

            <div className="panel-heading">
              <span className="step">02</span>
              <div>
                <h2>Deployment Target</h2>
                <p>Select your deployment environment.</p>
              </div>
            </div>

            <div className="target-grid">
              {[
                ["linux-container", "◈", "Linux Container", "Docker / Railpack"],
                ["iis", "▤", "IIS", "Windows Web Server"],
                ["windows-service", "⚙", "Windows Service", ".NET Background Service"],
              ].map(([value, icon, name, description]) => (
                <button
                  key={value}
                  type="button"
                  className={`target-card ${form.deployment_target === value ? "selected" : ""
                    }`}
                  onClick={() => update("deployment_target", value)}
                >
                  <span className="target-icon">{icon}</span>
                  <strong>{name}</strong>
                  <small>{description}</small>
                </button>
              ))}
            </div>

            <div className="separator" />

            <div className="panel-heading">
              <span className="step">03</span>
              <div>
                <h2>Environment Settings</h2>
                <p>Configure deployment-specific parameters.</p>
              </div>
            </div>

            <label>Agent Pool</label>
            <input
              value={form.agent_pool}
              onChange={(e) => update("agent_pool", e.target.value)}
              placeholder={
                form.deployment_target === "linux-container"
                  ? "AutoPipeline-Linux"
                  : "AutoPipeline-Windows"
              }
            />

            {(targetFields[form.deployment_target] || []).map((field) => (
              <div key={field.key}>
                <label>{field.label}</label>
                <input
                  type={field.type || "text"}
                  value={field.type === "checkbox" ? undefined : form[field.key]}
                  checked={field.type === "checkbox" ? form[field.key] : undefined}
                  onChange={(e) => update(field.key, field.type === "checkbox" ? e.target.checked : e.target.value)}
                  placeholder={field.placeholder}
                />
              </div>
            ))}

            <button
              className="primary-button"
              onClick={preview}
              disabled={loading || !form.repository_url.trim() || !form.deployment_target}
            >
              {loading ? "Processing..." : "⚡ Generate Pipeline"}
            </button>
          </section>

          <section className="panel output-panel">
            <div className="output-header">
              <div>
                <h2>Pipeline Output</h2>
                <p>Generated Azure DevOps YAML</p>
              </div>
              <span className={`output-badge ${yaml ? "ready" : ""}`}>
                {yaml ? "Generated" : "Awaiting Input"}
              </span>
            </div>

            {error && <div className="error-message">{error}</div>}

            <div className="code-window">
              <div className="code-topbar">
                <span>azure-pipelines.generated.yml</span>
                {yaml && (
                  <button onClick={() => navigator.clipboard.writeText(yaml)}>
                    Copy YAML
                  </button>
                )}
              </div>

              {yaml ? (
                <pre>{yaml}</pre>
              ) : (
                <div className="empty-state">
                  <div className="empty-icon">{"</>"}</div>
                  <h3>No pipeline generated yet</h3>
                  <p>
                    Configure your repository and deployment target,
                    then generate a pipeline to preview the YAML.
                  </p>
                </div>
              )}
            </div>

            {result && (
              <div className="result-info">
                <strong>Status:</strong> {result.status || "Preview ready"}
                {result.pull_request_id && (
                  <div>Pull Request ID: {result.pull_request_id}</div>
                )}
              </div>
            )}

            <button
              className="secondary-button"
              onClick={createPR}
              disabled={!yaml || loading}
            >
              Create Pull Request
            </button>

            <p className="output-note">
              Preview generates YAML without pushing changes.
              Creating a PR requires an Azure DevOps connection.
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}
