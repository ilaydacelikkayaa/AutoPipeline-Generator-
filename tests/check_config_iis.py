from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from backend.config_loader import load_pipeline_config
from backend.pipeline_orchestrator import generate_for_repository


def test_iis_config():
    config = {
        "project": {
            "name": "TestWebApp",
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
            "target": "iis",
            "agent_pool": "AutoPipeline-Windows",
            "app_pool_name": "TestAppPool",
            "site_path": r"C:\inetpub\wwwroot\TestApp",
            "health_check_url": "http://localhost:8080/health",
        },
    }

    with TemporaryDirectory() as temp_dir:
        repository = Path(temp_dir)
        (repository / "App.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>')
        config_path = repository / "config.yaml"

        config_path.write_text(
            yaml.safe_dump(config, sort_keys=False),
            encoding="utf-8",
        )

        loaded = load_pipeline_config(str(config_path))
        assert loaded["deployment_target"] == "iis"

        generated_yaml = generate_for_repository(
            repository_path=repository,
            config_path=str(config_path),
        )

        pipeline = yaml.safe_load(generated_yaml)
        jobs = pipeline["jobs"]

        assert [job["job"] for job in jobs] == ["Build", "Deploy"]

        deploy_job = jobs[1]
        assert deploy_job["pool"]["name"] == "AutoPipeline-Windows"

        steps = deploy_job["steps"]

        deploy_step = next(
            step
            for step in steps
            if step.get("displayName") == "Deploy IIS Application"
        )

        environment = deploy_step["env"]

        assert environment["APP_POOL_NAME"] == "TestAppPool"
        assert environment["SITE_PATH"] == r"C:\inetpub\wwwroot\TestApp"
        assert environment["HEALTH_CHECK_URL"] == "http://localhost:8080/health"

    print("CONFIG IIS PASSED")


if __name__ == "__main__":
    test_iis_config()
