from pathlib import Path
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
import yaml

from backend.pipeline_orchestrator import (
    generate_for_discovered_repository,
)


class DeploymentTargetsTest(unittest.TestCase):

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repository = Path(directory.name)
        (self.repository / "App.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>')
        (self.repository / "Program.cs").write_text("builder.Services.AddWindowsService();")
        mock = patch("backend.pipeline_orchestrator.generate_railpack_plan", return_value={
            "steps": [{"name": "build"}], "deploy": {"startCommand": "dotnet App.dll"},
        })
        mock.start()
        self.addCleanup(mock.stop)

    def generate(self, **kwargs):
        result = generate_for_discovered_repository(
            repository_path=self.repository,
            repository_name="TestApplication",
            **kwargs,
        )
        return yaml.safe_load(result)

    def test_linux_container(self):
        pipeline = self.generate(
            deployment_target="linux-container",
            container_port=8080,
        )

        build, deploy = pipeline["jobs"]

        self.assertEqual(build["job"], "Build")
        self.assertEqual(deploy["job"], "Deploy")
        self.assertEqual(
            deploy["pool"]["name"],
            "AutoPipeline-Linux",
        )

        scripts = [step.get("script", "") for step in deploy["steps"]]

        self.assertTrue(any("-p 8082:8080" in script for script in scripts))

    def test_iis(self):
        pipeline = self.generate(
            deployment_target="iis",
            app_pool_name="TestAppPool",
            site_path=r"C:\inetpub\wwwroot\TestApp",
            health_check_url="http://localhost:8080/health",
        )

        build, deploy = pipeline["jobs"]
        steps = deploy["steps"]

        self.assertEqual(build["job"], "Build")
        self.assertEqual(deploy["pool"]["name"], "AutoPipeline-Windows")
        self.assertEqual(len(steps), 3)
        self.assertEqual(
            steps[0]["task"],
            "DownloadPipelineArtifact@2",
        )
        self.assertEqual(
            steps[2]["env"]["APP_POOL_NAME"],
            "TestAppPool",
        )

    def test_windows_service(self):
        pipeline = self.generate(
            deployment_target="windows-service",
            service_name="TestWorker",
            install_path=r"C:\Services\TestWorker",
        )

        build, deploy = pipeline["jobs"]
        steps = deploy["steps"]

        self.assertEqual(build["job"], "Build")
        self.assertEqual(deploy["pool"]["name"], "AutoPipeline-Windows")
        self.assertEqual(len(steps), 3)
        self.assertEqual(
            steps[2]["env"]["SERVICE_NAME"],
            "TestWorker",
        )

    def test_missing_iis_config(self):
        with self.assertRaises(ValueError):
            self.generate(deployment_target="iis")

    def test_missing_service_config(self):
        with self.assertRaises(ValueError):
            self.generate(deployment_target="windows-service")

    def test_invalid_target(self):
        with self.assertRaises(ValueError):
            self.generate(deployment_target="unknown-target")


if __name__ == "__main__":
    unittest.main()
