from pathlib import Path
import difflib
from backend.azure_devops_service import (
    clone_repository,
    ensure_pull_request,
    discover_repositories,
)
from backend.config_loader import load_pipeline_config
from backend.pipeline_orchestrator import (
    generate_for_discovered_repository,
)



def compare_pipeline_yaml(
    repository_path: Path,
    generated_yaml: str,
    filename: str = "azure-pipelines.generated.yml",
) -> dict:
    """
    Yeni üretilen YAML ile repository'deki
    mevcut YAML dosyasını karşılaştırır.
    """

    yaml_path = repository_path / filename

    if yaml_path.exists():
        existing_yaml = yaml_path.read_text(encoding="utf-8")
    else:
        existing_yaml = ""

    has_changes = existing_yaml != generated_yaml

    diff = "".join(
        difflib.unified_diff(
            existing_yaml.splitlines(keepends=True),
            generated_yaml.splitlines(keepends=True),
            fromfile="existing",
            tofile="generated",
        )
    )

    return {
        "has_changes": has_changes,
        "file_exists": yaml_path.exists(),
        "diff": diff,
    }


def decide_pipeline_deployment(comparison: dict) -> str:
    if not comparison["has_changes"]:
        return "SKIP"

    if comparison["file_exists"]:
        return "UPDATE"

    return "CREATE"


import subprocess


def create_deployment_branch(
    repository_path: Path,
    branch_name: str = "automation/pipeline-update",
) -> str:

    result = subprocess.run(
        [
            "git",
            "switch",
            "-c",
            branch_name,
        ],
        cwd=repository_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )

    return result.stdout.strip()


def commit_pipeline_yaml(
    repository_path: Path,
    generated_yaml: str,
    filename: str = "azure-pipelines.generated.yml",
) -> str:

    repository_path = repository_path.resolve()
    yaml_path = repository_path / filename

    if yaml_path.exists() and yaml_path.is_symlink():
        raise ValueError("YAML dosyası sembolik bağlantı olamaz.")

    if not yaml_path.parent.resolve().is_relative_to(repository_path):
        raise ValueError("Dosya repository dışında olamaz.")

    if filename != "azure-pipelines.generated.yml":
        raise ValueError("Yalnızca üretilen YAML dosyası yönetilebilir.")

    yaml_path.write_text(generated_yaml, encoding="utf-8")

    subprocess.run(
        ["git", "add", "--", filename],
        cwd=repository_path,
        check=True,
        capture_output=True,
        text=True,
    )

    result = subprocess.run(
        [
            "git",
            "commit",
            "--only",
            "-m",
            "Update generated pipeline",
            "--",
            filename,
        ],
        cwd=repository_path,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def push_pipeline_branch(
    repository_path: Path,
    branch_name: str = "automation/pipeline-update",
) -> str:

    result = subprocess.run(
        [
            "git",
            "push",
            "--set-upstream",
            "origin",
            branch_name,
        ],
        cwd=repository_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )

    return result.stderr.strip()


def deploy_repository_pipeline(
    repository_url: str,
    repository_name: str,
    project_name: str,
    dry_run: bool = True,
    default_branch: str = "main",
    deployment_target: str | None = None,
    agent_pool: str | None = None,
    app_pool_name: str | None = None,
    site_path: str | None = None,
    health_check_url: str | None = None,
    service_name: str | None = None,
    install_path: str | None = None,
    container_port: int | None = None,
    host_port: int | None = None,
    build_platform: str | None = None,
    build_engine: str | None = None,
    dotnet_project: str | None = None,
    dotnet_framework: str | None = None,
    dotnet_sdk_version: str | None = None,
    dotnet_runtime: str | None = None,
    dotnet_self_contained: bool | None = None,
    agent_name: str | None = None,

) -> dict:

    temp, path = clone_repository(
        repository_url,
        branch=default_branch,
    )
    path = Path(path)

    try:
        generated_yaml = generate_for_discovered_repository(
            path,
            repository_name,
            deployment_target=deployment_target,
            agent_pool=agent_pool,
            app_pool_name=app_pool_name,
            site_path=site_path,
            health_check_url=health_check_url,
            service_name=service_name,
            install_path=install_path,
            container_port=container_port,
            host_port=host_port,
            build_platform=build_platform,
            build_engine=build_engine,
            dotnet_project=dotnet_project,
            dotnet_framework=dotnet_framework,
            dotnet_sdk_version=dotnet_sdk_version,
            dotnet_runtime=dotnet_runtime,
            dotnet_self_contained=dotnet_self_contained,
            agent_name=agent_name,

            branch=default_branch,
        )

        comparison = compare_pipeline_yaml(
            path,
            generated_yaml,
        )

        decision = decide_pipeline_deployment(comparison)

        if decision == "SKIP":
            return {
                "status": "SKIP",
                "repository": repository_name,
                "reason": "Generated YAML is identical to existing YAML",
                "has_changes": comparison["has_changes"],
                "file_exists": comparison["file_exists"],
            }
        if dry_run:
            return {
                "status": "DRY_RUN",
                "repository": repository_name,
                "decision": decision,
                "diff": comparison["diff"],
            }

        branch_name = "automation/pipeline-update"

        # Mevcut branch'i getir veya yeni branch oluştur
        prepare_deployment_branch(path, branch_name)

        ancestor_check = subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                f"origin/{default_branch}",
                "HEAD",
            ],
            cwd=path,
            capture_output=True,
            text=True,
        )

        if ancestor_check.returncode != 0:
            raise RuntimeError(
                "Automation branch hedef branch ile güncel değil. "
                "Manuel kontrol gerekiyor."
            )

        changed_files = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                f"origin/{default_branch}...HEAD",
            ],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )

        unexpected_files = [
            filename
            for filename in changed_files.stdout.splitlines()
            if filename != "azure-pipelines.generated.yml"
        ]

        if unexpected_files:
            raise RuntimeError(
                "Automation branch beklenmeyen dosya "
                f"değişiklikleri içeriyor: {unexpected_files}"
            )

        # Otomasyon branch'indeki YAML'ı karşılaştır
        branch_comparison = compare_pipeline_yaml(
            path,
            generated_yaml,
        )

        if branch_comparison["has_changes"]:

            commit_pipeline_yaml(
                path,
                generated_yaml,
            )

            push_pipeline_branch(
                path,
                branch_name,
            )

        # Branch hedef branch ile aynıysa PR açılacak değişiklik yoktur.
        branch_diff = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                f"origin/{default_branch}...HEAD",
                "--",
                "azure-pipelines.generated.yml",
            ],
            cwd=path,
            capture_output=True,
            text=True,
        )
        if branch_diff.returncode == 0:
            return {
                "status": "SKIP",
                "repository": repository_name,
                "reason": "Automation branch üzerinde PR gerektiren YAML farkı yok",
            }
        if branch_diff.returncode != 1:
            raise RuntimeError(
                f"Git diff kontrolü başarısız: {branch_diff.stderr.strip()}"
            )

        # PR zaten varsa onu kullan, yoksa oluştur
        pr = ensure_pull_request(
            project_name,
            repository_name,
            branch_name,
            target_branch=default_branch,
        )

        return {
            "status": "PR_READY",
            "repository": repository_name,
            "decision": decision,
            "branch": branch_name,
            "pull_request_id": pr["pullRequestId"],
        }

    finally:
        temp.cleanup()


def deploy_all_repositories(
    project_name: str,
    dry_run: bool = True,
) -> list[dict]:

    repositories = discover_repositories(project_name)
    results = []
    config = load_pipeline_config("config.yaml")
    for repo in repositories:
        print(f"\nİşleniyor: {repo['name']}")
        if not repo.get("default_branch"):
            results.append(
                {
                    "repository": repo["name"],
                    "status": "SKIP",
                    "reason": "Repository has no default branch",
                }
            )
            continue
        is_configured_repo = repo["name"] == config["project_name"]

        deployment_target = config["deployment_target"] if is_configured_repo else None

        agent_pool = config["agent_pool"] if is_configured_repo else None
        try:
            result = deploy_repository_pipeline(
                repository_url=repo["remote_url"],
                repository_name=repo["name"],
                project_name=project_name,
                default_branch=repo["default_branch"].removeprefix("refs/heads/"),
                dry_run=dry_run,
                deployment_target=deployment_target,
                agent_pool=agent_pool,
                app_pool_name=(
                    config.get("app_pool_name") if is_configured_repo else None
                ),
                site_path=config.get("site_path") if is_configured_repo else None,
                health_check_url=(
                    config.get("health_check_url") if is_configured_repo else None
                ),
                service_name=config.get("service_name") if is_configured_repo else None,
                install_path=config.get("install_path") if is_configured_repo else None,
                host_port=config.get("host_port") if is_configured_repo else None,
                build_platform=config.get("build_platform") if is_configured_repo else None,
                build_engine=config.get("build_engine") if is_configured_repo else None,
                dotnet_project=config.get("dotnet_project") if is_configured_repo else None,
                dotnet_framework=config.get("dotnet_framework") if is_configured_repo else None,
                dotnet_sdk_version=config.get("dotnet_sdk_version") if is_configured_repo else None,
                dotnet_runtime=config.get("dotnet_runtime") if is_configured_repo else None,
                dotnet_self_contained=config.get("dotnet_self_contained") if is_configured_repo else None,
                agent_name=config.get("agent_name") if is_configured_repo else None,

                container_port=(
                    config.get("container_port") if is_configured_repo else None
                ),
            )

            results.append(result)

        except Exception as e:
            print(f"HATA: {repo['name']} → {e}")

            results.append(
                {
                    "repository": repo["name"],
                    "status": "ERROR",
                    "error": str(e),
                }
            )

    return results


def prepare_deployment_branch(
    repository_path: Path,
    branch_name: str = "automation/pipeline-update",
) -> None:

    remote_check = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        cwd=repository_path,
        capture_output=True,
        text=True,
        check=True,
    )

    if remote_check.stdout.strip():

        # Shallow clone ise Git geçmişini tamamla
        shallow_check = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=repository_path,
            capture_output=True,
            text=True,
            check=True,
        )

        if shallow_check.stdout.strip() == "true":
            subprocess.run(
                ["git", "fetch", "--unshallow", "origin"],
                cwd=repository_path,
                check=True,
            )

        # Hedef branch'i güncel olarak getir
        subprocess.run(
            ["git", "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"],
            cwd=repository_path,
            check=True,
        )

        # Mevcut otomasyon branch'ine geç
        subprocess.run(
            ["git", "switch", "-c", branch_name, f"origin/{branch_name}"],
            cwd=repository_path,
            check=True,
        )

    else:
        create_deployment_branch(repository_path, branch_name)
