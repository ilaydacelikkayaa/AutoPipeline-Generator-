import json
import subprocess
from pathlib import Path


def generate_railpack_plan(
    project_path: Path,
    build_variables: dict[str, str] | None = None,
):
    command = ["railpack", "plan", str(project_path)]

    for key, value in (build_variables or {}).items():
        if not key.startswith("RAILPACK_"):
            raise ValueError(f"Geçersiz Railpack ayarı: {key}")

        command.extend(["--env", f"{key}={value}"])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )

        plan = json.loads(result.stdout)

        if not isinstance(plan, dict):
            raise ValueError("Railpack planı JSON nesnesi olmalı.")

        return plan

    except subprocess.TimeoutExpired:
        raise RuntimeError("Railpack analizi zaman aşımına uğradı.")

    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Railpack analizi başarısız: {error.stderr}") from error

    except json.JSONDecodeError as error:
        raise RuntimeError("Railpack geçerli bir JSON planı döndürmedi.") from error
