from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from backend.pipeline_orchestrator import (
    generate_for_repository,
    generate_for_discovered_repository,
)


def expect_value_error(action, expected_field):
    try:
        action()
    except ValueError as error:
        assert expected_field in str(error), str(error)
        return

    raise AssertionError(f"ValueError bekleniyordu: {expected_field}")


def test_missing_windows_service_path():
    with TemporaryDirectory() as temp_dir:
        repository = Path(temp_dir)
        config_path = repository / "config.yaml"

        config = {
            "project": {"name": "Worker", "path": "."},
            "pipeline": {"vm_image": "ubuntu-latest"},
            "deployment": {
                "target": "windows-service",
                "service_name": "WorkerService",
                # install_path deliberately missing
            },
        }

        config_path.write_text(
            yaml.safe_dump(config),
            encoding="utf-8",
        )

        expect_value_error(
            lambda: generate_for_repository(
                repository,
                str(config_path),
            ),
            "install_path",
        )


def test_missing_iis_app_pool():
    with TemporaryDirectory() as temp_dir:
        repository = Path(temp_dir)
        config_path = repository / "config.yaml"

        config = {
            "project": {"name": "WebApp", "path": "."},
            "pipeline": {"vm_image": "ubuntu-latest"},
            "deployment": {
                "target": "iis",
                "site_path": r"C:\inetpub\wwwroot\WebApp",
                "health_check_url": "http://localhost/health",
                # app_pool_name deliberately missing
            },
        }

        config_path.write_text(
            yaml.safe_dump(config),
            encoding="utf-8",
        )

        expect_value_error(
            lambda: generate_for_repository(
                repository,
                str(config_path),
            ),
            "app_pool_name",
        )


def test_missing_discovered_service_path():
    with TemporaryDirectory() as temp_dir:
        expect_value_error(
            lambda: generate_for_discovered_repository(
                repository_path=Path(temp_dir),
                repository_name="Worker",
                deployment_target="windows-service",
                service_name="WorkerService",
            ),
            "install_path",
        )


def test_missing_discovered_iis_pool():
    with TemporaryDirectory() as temp_dir:
        expect_value_error(
            lambda: generate_for_discovered_repository(
                repository_path=Path(temp_dir),
                repository_name="WebApp",
                deployment_target="iis",
                site_path=r"C:\inetpub\wwwroot\WebApp",
                health_check_url="http://localhost/health",
            ),
            "app_pool_name",
        )


if __name__ == "__main__":
    test_missing_windows_service_path()
    test_missing_iis_app_pool()
    test_missing_discovered_service_path()
    test_missing_discovered_iis_pool()

    print("INVALID DEPLOYMENT TESTS PASSED")
