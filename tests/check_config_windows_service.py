from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import yaml

from backend.pipeline_orchestrator import generate_for_repository

with TemporaryDirectory() as temp:
    config_path = Path(temp) / "config.yaml"
    (Path(temp) / "Worker.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk.Worker"><PropertyGroup><TargetFramework>net8.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')

    (Path(temp) / "Program.cs").write_text("builder.Services.AddWindowsService();")

    config = {
        "project": {
            "name": "TestWorker",
            "path": ".",
            "branch": "main",
        },
        "pipeline": {
            "vm_image": "ubuntu-latest",
            "build_engine": "dotnet",
        },
        "artifact": {
            "name": "application-build",
        },
        "deployment": {
            "target": "windows-service",
            "agent_pool": "AutoPipeline-Windows",
            "service_name": "TestWorker",
            "install_path": r"C:\Services\TestWorker",
        },
    }

    config_path.write_text(
        yaml.safe_dump(config),
        encoding="utf-8",
    )
    from backend.config_loader import load_pipeline_config

    loaded_config = load_pipeline_config(str(config_path))

    print("Loaded deployment target:", loaded_config.get("deployment_target"))
    print("Loaded config:", loaded_config)
    with patch(
        "backend.pipeline_orchestrator.generate_railpack_plan",
        side_effect=AssertionError("Windows Service için Railpack çağrılmamalı"),
    ):
        result = generate_for_repository(
            repository_path=Path(temp),
            config_path=str(config_path),
        )

    pipeline = yaml.safe_load(result)
    print("Generated jobs:", [job["job"] for job in pipeline["jobs"]])
    assert pipeline["jobs"][0]["job"] == "Build"
    assert pipeline["jobs"][1]["job"] == "Deploy"

    deploy_steps = pipeline["jobs"][1]["steps"]
    deploy_text = str(deploy_steps)
    for index, step in enumerate(deploy_steps):
        print(f"\nSTEP {index}")
        print(yaml.safe_dump(step, sort_keys=False, allow_unicode=True))
    deploy_step = deploy_steps[2]

    environment = deploy_step["env"]
    assert environment["SERVICE_NAME"] == "TestWorker"
    assert environment["INSTALL_PATH"] == r"C:\Services\TestWorker"
    print("CONFIG WINDOWS SERVICE PASSED")
