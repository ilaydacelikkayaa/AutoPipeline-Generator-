import ast
import re
import tomllib
from pathlib import Path


def adapt_start_command(
    start_command: str | None,
    project_path: str | Path,
) -> str | None:
    if not start_command:
        return start_command

    project_path = Path(project_path)
    if start_command.strip() == "python main.py":
        source = project_path / "main.py"
        if not source.is_file():
            return start_command
        try:
            tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeError):
            return start_command
        # Keep executable entry points supplied by the repository.
        if any(isinstance(node, ast.If) and "__name__" in ast.unparse(node.test)
               for node in tree.body):
            return start_command
        factories = set()
        modules = set()
        runners = set()
        runtime_modules = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
                factories.update(alias.asname or alias.name for alias in node.names
                                 if alias.name == "FastAPI")
            elif isinstance(node, ast.ImportFrom) and node.module == "uvicorn":
                runners.update(alias.asname or alias.name for alias in node.names if alias.name == "run")
            elif isinstance(node, ast.Import):
                modules.update(alias.asname or alias.name for alias in node.names
                               if alias.name == "fastapi")
                runtime_modules.update(alias.asname or alias.name for alias in node.names if alias.name == "uvicorn")
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                function = node.value.func
                if (isinstance(function, ast.Name) and function.id in runners) or (
                    isinstance(function, ast.Attribute) and function.attr == "run"
                    and isinstance(function.value, ast.Name) and function.value.id in runtime_modules
                ):
                    return start_command
        applications = []
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            factory = value.func
            is_fastapi = (isinstance(factory, ast.Name) and factory.id in factories) or (
                isinstance(factory, ast.Attribute) and factory.attr == "FastAPI"
                and isinstance(factory.value, ast.Name) and factory.value.id in modules
            )
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if is_fastapi:
                applications.extend(target.id for target in targets if isinstance(target, ast.Name))
        if len(applications) != 1:
            return start_command
        requirements = project_path / "requirements.txt"
        dependencies = requirements.read_text(encoding="utf-8", errors="replace").splitlines() if requirements.is_file() else []
        pyproject = project_path / "pyproject.toml"
        if pyproject.is_file():
            metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            dependencies.extend(metadata.get("project", {}).get("dependencies", []))
            poetry = metadata.get("tool", {}).get("poetry", {}).get("dependencies", {})
            dependencies.extend(poetry.keys())
            fastapi = poetry.get("fastapi")
            if isinstance(fastapi, dict) and "standard" in fastapi.get("extras", []):
                dependencies.append("fastapi[standard]")
        if not any(re.match(r"^\s*(?:uvicorn(?:\[[^\]]+\])?|fastapi\[standard\])\s*(?:[<>=!~;#@]|$)", dependency, re.IGNORECASE)
                   for dependency in dependencies):
            raise ValueError("FastAPI başlangıcı için uvicorn bağımlılığı gerekli.")
        return f"python -m uvicorn main:{applications[0]} --host 0.0.0.0 --port ${{PORT:-8080}}"

    if "*/build/libs/*jar" in start_command and any(
        (project_path / name).is_file() for name in ("build.gradle", "build.gradle.kts")
    ):
        return (
            "JAR=$(find /app/build/libs -maxdepth 1 "
            '-type f -name "*.jar" ! -name "*-plain.jar" '
            "-print -quit); "
            'test -n "$JAR" || exit 1; '
            'exec java $JAVA_OPTS -Dserver.port=${PORT:-8080} -jar "$JAR"'
        )

    return start_command
