from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

from backend.pipeline_orchestrator import (
    generate_for_discovered_repository,
)


def test_linux_regression():
    with TemporaryDirectory() as temp_dir:
        repository = Path(temp_dir)
        (repository / "requirements.txt").write_text("flask\n")

        with patch(
            "backend.pipeline_orchestrator.resolve_runtime_variables",
            return_value={},
        ), patch(
            "backend.pipeline_orchestrator.generate_railpack_plan",
            return_value={"steps": [{"name": "build"}]},
        ), patch(
            "backend.pipeline_orchestrator.create_pipeline_plan",
            return_value={
                "project_path": ".",
                "container_port": 8080,
            },
        ):
            generated_yaml = generate_for_discovered_repository(
                repository_path=repository,
                repository_name="TestLinuxApp",
                deployment_target="linux-container",
                container_port=8080,
            )

        pipeline = yaml.safe_load(generated_yaml)
        jobs = pipeline["jobs"]

        assert [job["job"] for job in jobs] == ["Build", "Deploy"]

        deploy_job = jobs[1]

        assert deploy_job["pool"]["name"] == "AutoPipeline-Linux"

        steps_text = str(deploy_job["steps"])

        assert "docker" in steps_text.lower()
        assert "8080" in steps_text
        assert "8082" in steps_text

    print("LINUX CONTAINER REGRESSION PASSED")


if __name__ == "__main__":
    test_linux_regression()
