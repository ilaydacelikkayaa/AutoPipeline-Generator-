# AutoPipeline Generator

Generate Azure Pipelines YAML from repository analysis, preview the result in a React interface, and prepare an Azure Repos pull request after confirmation.

## Components

- **FastAPI backend:** repository analysis, pipeline previews and pull request requests.
- **Repository analyzer:** project discovery, language detection and build strategy selection.
- **Pipeline generation:** Railpack, Dockerfile and .NET build steps with artifact handling.
- **Deployment:** Linux containers, IIS and Windows Services.
- **Azure DevOps integration:** Azure CLI repository discovery, pipeline comparison and pull request reuse.
- **React frontend:** deployment settings, YAML previews and a confirmation flow for pull requests.

## Local setup

Use Python 3.11 or later (the source imports `tomllib`), Node.js/npm, Git and the external tools required by the selected workflow: Railpack, Docker and Azure CLI with Azure DevOps support.

A backend dependency manifest is not yet included. The source imports FastAPI, Pydantic, PyYAML and GitPython; install these and an ASGI server such as Uvicorn in your own virtual environment. Dependency versions are not pinned or verified by this publication.

From the project root, start the backend:

```sh
uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

Start the frontend separately:

```sh
cd frontend
npm ci
npm run dev
```

The frontend currently calls `http://localhost:8002`. Backend CORS allows local frontend ports 5173 and 5174. `config.yaml` contains an example Linux container configuration; review its project and agent pool settings before using it.

Authenticate Azure CLI locally when using Azure DevOps operations. Never commit tokens, passwords, `.env` files or CLI credential stores. Frontend code and any `VITE_*` variables are public and must not contain secrets.

## Checks

```sh
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v
npm --prefix frontend run lint
npm --prefix frontend run build
```

The four `tests/check_*.py` scripts are supplementary checks and are not collected by standard unittest discovery. Run them separately from the project root with the root on Python's module search path.

Tests use fixtures and mocks for external operations. Passing local tests does not establish successful deployments on real Linux or Windows hosts. Preview and dry-run operations should precede any confirmed pull request or deployment operation.

## Publication history

The initial commits import an existing project in architectural groups at publication time. They do not reconstruct its original development timeline. Intermediate import commits can depend on components added by subsequent commits; the complete snapshot is the final import commit.

Local backups, credentials, dependency folders, build output, generated pipeline files and environment-specific investigation reports are intentionally excluded. Existing application source is preserved during publication.
