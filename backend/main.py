from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
import subprocess
from backend.pipeline_deployer import deploy_repository_pipeline
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import traceback
from backend.repository_analyzer import clone_repository
from backend.pipeline_orchestrator import generate_for_discovered_repository

app = FastAPI(title="AutoPipeline Generator API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {"message": "AutoPipeline Generator API"}


@app.get("/health")
def health():
    return {"status": "healthy"}


class RepositoryRequest(BaseModel):
    repo_url: str


@app.post("/analyze")
def analyze_repository(request: RepositoryRequest):
    try:
        result = clone_repository(request.repo_url)
        files = result["files"]
        build_analysis = result["build_analysis"]

        return {
            "repository": request.repo_url,
            "file_count": len(files),
            "files": files,
            "language_analysis": result["language_analysis"],
            "build_analysis": build_analysis,
            "package_manager_analysis": result["package_manager_analysis"],
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


class PipelineRequest(BaseModel):
    repository_url: str
    repository_name: str = ""
    deployment_target: str
    default_branch: str = Field(default="main", min_length=1)
    agent_pool: str | None = None
    container_port: int | None = Field(default=None, ge=1, le=65535)
    host_port: int | None = Field(default=None, ge=1, le=65535)
    build_platform: str | None = None
    build_engine: str | None = None
    app_pool_name: str | None = None
    site_path: str | None = None
    health_check_url: str | None = None
    service_name: str | None = None
    install_path: str | None = None
    dotnet_project: str | None = None
    dotnet_framework: str | None = None
    dotnet_sdk_version: str | None = None
    dotnet_runtime: str | None = None
    dotnet_self_contained: bool | None = None
    agent_name: str | None = None


class PullRequestRequest(PipelineRequest):
    project_name: str
    confirmed: bool = False
    dry_run: bool = True


def validate_repository_url(url: str) -> None:
    parsed = urlparse(url)

    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"github.com", "dev.azure.com"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Geçerli bir HTTPS GitHub veya Azure DevOps URL'si girin.")

    if not parsed.path.strip("/"):
        raise ValueError("Repository adresi eksik.")


@app.post("/api/pipeline/preview")
def preview_pipeline(request: PipelineRequest):
    try:
        validate_repository_url(request.repository_url)

        if request.deployment_target not in {
            "linux-container",
            "iis",
            "windows-service",
        }:
            raise ValueError("Desteklenmeyen deployment hedefi.")

        repository_name = request.repository_name.strip()

        if not repository_name:
            repository_name = (
                request.repository_url.rstrip("/").split("/")[-1].removesuffix(".git")
            )

        with TemporaryDirectory(prefix="autopipeline-preview-") as temp_dir:
            repository_path = Path(temp_dir) / "repository"

            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    request.default_branch,
                    "--",
                    request.repository_url,
                    str(repository_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )

            yaml_content = generate_for_discovered_repository(
                repository_path=repository_path,
                repository_name=repository_name,
                deployment_target=request.deployment_target,
                agent_pool=request.agent_pool,
                app_pool_name=request.app_pool_name,
                site_path=request.site_path,
                health_check_url=request.health_check_url,
                service_name=request.service_name,
                install_path=request.install_path,
                container_port=request.container_port,
                host_port=request.host_port,
                build_platform=request.build_platform,
                build_engine=request.build_engine,
                dotnet_project=request.dotnet_project,
                dotnet_framework=request.dotnet_framework,
                dotnet_sdk_version=request.dotnet_sdk_version,
                dotnet_runtime=request.dotnet_runtime,
                dotnet_self_contained=request.dotnet_self_contained,
                agent_name=request.agent_name,
                branch=request.default_branch,
            )

        return {
            "status": "PREVIEW_READY",
            "repository": repository_name,
            "deployment_target": request.deployment_target,
            "yaml": yaml_content,
        }

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except subprocess.CalledProcessError:
        raise HTTPException(
            status_code=400,
            detail="Repository klonlanamadı. URL ve erişim izinlerini kontrol edin.",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Repository klonlama işlemi zaman aşımına uğradı.",
        )
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Pipeline önizlemesi oluşturulamadı. Backend loglarını kontrol edin.",
        )


@app.post("/api/pipeline/pr")
def create_pipeline_pr(request: PullRequestRequest):
    if not request.dry_run and not request.confirmed:
        raise HTTPException(
            status_code=400,
            detail="PR oluşturmak için kullanıcı onayı gerekli.",
        )

    try:
        validate_repository_url(request.repository_url)

        if urlparse(request.repository_url).hostname != "dev.azure.com":
            raise ValueError("PR oluşturmak için Azure Repos URL'si kullanılmalı.")

        if request.deployment_target not in {
            "linux-container",
            "iis",
            "windows-service",
        }:
            raise ValueError("Desteklenmeyen deployment hedefi.")

        if not request.project_name.strip():
            raise ValueError("Azure DevOps proje adı gerekli.")

        if not request.repository_name.strip():
            raise ValueError("Repository adı gerekli.")

        result = deploy_repository_pipeline(
            repository_url=request.repository_url,
            repository_name=request.repository_name,
            project_name=request.project_name,
            dry_run=request.dry_run,
            default_branch=request.default_branch,
            deployment_target=request.deployment_target,
            agent_pool=request.agent_pool,
            app_pool_name=request.app_pool_name,
            site_path=request.site_path,
            health_check_url=request.health_check_url,
            service_name=request.service_name,
            install_path=request.install_path,
            container_port=request.container_port,
            host_port=request.host_port,
            build_platform=request.build_platform,
            build_engine=request.build_engine,
            dotnet_project=request.dotnet_project,
            dotnet_framework=request.dotnet_framework,
            dotnet_sdk_version=request.dotnet_sdk_version,
            dotnet_runtime=request.dotnet_runtime,
            dotnet_self_contained=request.dotnet_self_contained,
            agent_name=request.agent_name,
        )

        return result

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="PR işlemi başarısız. Backend loglarını kontrol edin.",
        )
