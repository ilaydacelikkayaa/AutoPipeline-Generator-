import re
from pathlib import Path


def resolve_runtime_variables(project_path: Path) -> dict[str, str]:
    """
    Projenin runtime ihtiyaçlarını tespit eder.
    Railpack için gerekli değişkenleri döndürür.
    """
    variables = {}

    gradle_files = [
        project_path / "build.gradle",
        project_path / "build.gradle.kts",
    ]

    for gradle_file in gradle_files:
        if not gradle_file.is_file():
            continue

        content = gradle_file.read_text(
            encoding="utf-8",
            errors="replace",
        )

        match = re.search(
            r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)",
            content,
        )

        if match:
            variables["RAILPACK_JDK_VERSION"] = match.group(1)
            break

    return variables
