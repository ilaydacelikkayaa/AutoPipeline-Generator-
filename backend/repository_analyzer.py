from urllib.parse import urlparse
import tempfile
from git import Repo
from pathlib import Path
from backend.build_detector import (
    find_build_files,
    detect_npm_scripts,
    detect_package_manager,
)
from backend.project_discovery import discover_projects
from backend.railpack_service import generate_railpack_plan
from backend.runtime_resolver import resolve_runtime_variables

from backend.technology_detector import detect_languages


def validate_repository_url(repo_url: str) -> bool:
    parsed = urlparse(repo_url)

    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None
        and parsed.query == ""  # ref=main
        and parsed.fragment == ""  # readme
        and len(parsed.path.strip("/").split("/")) == 2
        and all(parsed.path.strip("/").split("/"))
    )


def clone_repository(repo_url: str):
    if not validate_repository_url(repo_url):
        raise ValueError("Invalid GitHub repository URL")

    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Repo.clone_from(
            repo_url,
            temp_dir,
            depth=1,
            multi_options=["--no-tags"],
            allow_unsafe_options=False,
            allow_unsafe_protocols=False,
        )

        print("Repository cloned successfully!")
        print("Local path:", repo.working_tree_dir)
        repo_path = Path(repo.working_tree_dir).resolve()
        files = []

        for item in repo_path.rglob("*"):
            if item.is_file() and ".git" not in item.relative_to(repo_path).parts:
                relative_path = item.relative_to(repo_path)
                files.append(str(relative_path))

        build_files = find_build_files(repo_path, ["package.json"])

        build_analysis = []

        for file_path in build_files:
            scripts = detect_npm_scripts(file_path)

            build_analysis.append(
                {
                    "file": str(file_path.relative_to(repo_path)),
                    "build": scripts["build"],
                    "test": scripts["test"],
                    "error": scripts["error"],
                }
            )

        language_analysis = detect_languages(files)
        package_manager_analysis = detect_package_manager(repo_path)

        project_directories = discover_projects(repo_path)

        railpack_analysis = []

        for project_path in project_directories:
            relative_path = str(project_path.relative_to(repo_path))
            runtime_variables = resolve_runtime_variables(project_path)
            try:
                plan = generate_railpack_plan(
                    project_path,
                    build_variables=runtime_variables,
                )

                steps = plan.get("steps", [])

                if not steps:
                    railpack_analysis.append(
                        {
                            "project_path": relative_path,
                            "status": "no_build_plan",
                            "plan": None,
                        }
                    )
                    continue

                railpack_analysis.append(
                    {
                        "project_path": relative_path,
                        "status": "success",
                        "plan": plan,
                    }
                )

            except (RuntimeError, OSError, ValueError) as error:
                railpack_analysis.append(
                    {
                        "project_path": relative_path,
                        "status": "error",
                        "error": str(error),
                    }
                )

        return {
            "files": sorted(files),
            "language_analysis": language_analysis,
            "build_analysis": build_analysis,
            "package_manager_analysis": package_manager_analysis,
            "railpack_analysis": railpack_analysis,
        }
