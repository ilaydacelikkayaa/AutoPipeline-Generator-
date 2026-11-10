from pathlib import Path

from backend.build_detector import find_build_files

PROJECT_FILES = [
    "package.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
]


def discover_projects(repo_path: Path):
    repo_path = repo_path.resolve()

    found_files = find_build_files(repo_path, PROJECT_FILES)

    project_directories = {repo_path}

    for file_path in found_files:
        project_directories.add(file_path.parent)

    return sorted(
        project_directories, key=lambda path: str(path.relative_to(repo_path))
    )
