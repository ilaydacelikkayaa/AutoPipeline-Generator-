import json
import subprocess

from pathlib import Path
import tempfile


def discover_repositories(project_name: str):
    command = [
        "az",
        "repos",
        "list",
        "--project",
        project_name,
        "--output",
        "json",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )

    repositories = json.loads(result.stdout)

    return [
        {
            "name": repo["name"],
            "id": repo["id"],
            "remote_url": repo["remoteUrl"],
            "default_branch": repo.get("defaultBranch"),
        }
        for repo in repositories
    ]


def clone_repository(repository_url: str, branch: str = "main"):
    temporary_directory = tempfile.TemporaryDirectory()

    repository_path = Path(temporary_directory.name) / "repository"

    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                branch,
                repository_url,
                str(repository_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except Exception:
        temporary_directory.cleanup()
        raise

    return temporary_directory, repository_path


def create_pull_request(
    project_name: str,
    repository_name: str,
    source_branch: str,
    target_branch: str = "main",
) -> dict:

    command = [
        "az",
        "repos",
        "pr",
        "create",
        "--project",
        project_name,
        "--repository",
        repository_name,
        "--source-branch",
        source_branch,
        "--target-branch",
        target_branch,
        "--title",
        "AutoPipeline: Update generated YAML",
        "--description",
        "Generated pipeline update for review.",
        "--output",
        "json",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )

    return json.loads(result.stdout)


def list_active_pull_requests(
    project_name: str,
    repository_name: str,
) -> list[dict]:

    command = [
        "az",
        "repos",
        "pr",
        "list",
        "--project",
        project_name,
        "--repository",
        repository_name,
        "--status",
        "active",
        "--output",
        "json",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )

    return json.loads(result.stdout)


def find_existing_pull_request(
    project_name: str,
    repository_name: str,
    source_branch: str,
    target_branch: str = "main",
) -> dict | None:

    pull_requests = list_active_pull_requests(
        project_name,
        repository_name,
    )

    source_ref = f"refs/heads/{source_branch}"
    target_ref = f"refs/heads/{target_branch}"

    for pr in pull_requests:
        if pr["sourceRefName"] == source_ref and pr["targetRefName"] == target_ref:
            return pr

    return None


def ensure_pull_request(
    project_name: str,
    repository_name: str,
    source_branch: str,
    target_branch: str = "main",
) -> dict | None:
    existing = find_existing_pull_request(
        project_name, repository_name, source_branch, target_branch
    )
    if existing is not None:
        return existing
    else:
        existing = create_pull_request(
            project_name,
            repository_name,
            source_branch,
            target_branch,
        )
        return existing
