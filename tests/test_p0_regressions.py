from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.pipeline_plan import create_pipeline_plan, uses_port_variable
from backend.start_command_adapter import adapt_start_command


class StartupRegressionTest(unittest.TestCase):
    def test_plain_python_entrypoint_is_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text('print("hello")\n')
            self.assertEqual(
                adapt_start_command("python main.py", root), "python main.py"
            )

    def test_fastapi_uses_actual_application_name_and_final_port(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text(
                "from fastapi import FastAPI as API\nweb = API()\n"
            )
            (root / "requirements.txt").write_text("fastapi\nuvicorn[standard]\n")
            plan = create_pipeline_plan(
                {"deploy": {"startCommand": "python main.py"}},
                ".",
                repository_directory=root,
            )
            self.assertIn("python -m uvicorn main:web", plan["start_command"])
            self.assertTrue(plan["uses_port_variable"])

    def test_fastapi_runtime_dependency_is_required(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text("import fastapi\napp = fastapi.FastAPI()\n")
            with self.assertRaisesRegex(ValueError, "uvicorn"):
                adapt_start_command("python main.py", root)

    def test_existing_executable_fastapi_entrypoint_is_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
                'if __name__ == "__main__":\n    app.run()\n'
            )
            self.assertEqual(
                adapt_start_command("python main.py", root), "python main.py"
            )

    def test_gradle_jar_adapter_requires_gradle_evidence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            command = "java -jar */build/libs/*jar"
            self.assertEqual(adapt_start_command(command, root), command)
            (root / "build.gradle").write_text('plugins { id "java" }')
            self.assertIn('! -name "*-plain.jar"', adapt_start_command(command, root))

    def test_port_shell_forms(self):
        for command in ["$PORT", "${PORT}", "${PORT:-8080}"]:
            self.assertTrue(uses_port_variable({"deploy": {"startCommand": command}}))
        self.assertFalse(uses_port_variable({"deploy": {"startCommand": "$PORTABLE"}}))


class LinuxSettingsRegressionTest(unittest.TestCase):
    def test_health_url_and_ports_reach_deployment(self):
        from backend.deployment_generator import generate_deployment_steps

        steps = generate_deployment_steps(
            "linux-container",
            "app",
            "application-build",
            host_port=9001,
            container_port=9000,
            uses_port_variable=True,
            health_check_url="http://localhost:9001/health",
        )
        run = next(
            s["script"] for s in steps if s.get("displayName") == "Run Docker Container"
        )
        self.assertIn("-p 9001:9000", run)
        self.assertIn("-e PORT=9000", run)
        health = next(s for s in steps if s.get("displayName") == "HTTP Health Check")
        self.assertEqual(
            health["env"]["HEALTH_CHECK_URL"], "http://localhost:9001/health"
        )
        self.assertIn('"$HEALTH_CHECK_URL"', health["script"])
        self.assertNotIn("host.docker.internal", health["script"])

    def test_config_does_not_erase_detected_spring_port(self):
        from unittest.mock import patch
        import yaml
        from backend.pipeline_orchestrator import generate_for_repository

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pom.xml").write_text("<project />")
            resources = root / "src/main/resources"
            resources.mkdir(parents=True)
            (resources / "application.properties").write_text("server.port=9090\n")
            config = root / "config.yaml"
            config.write_text(
                yaml.safe_dump(
                    {
                        "project": {"name": "petclinic"},
                        "deployment": {"target": "linux-container", "host_port": 9091},
                        "pipeline": {"build_platform": "linux/amd64"},
                    }
                )
            )
            with patch(
                "backend.pipeline_orchestrator.generate_railpack_plan",
                return_value={
                    "steps": [{"name": "build"}],
                    "deploy": {"startCommand": "java -Dserver.port=$PORT -jar app.jar"},
                },
            ):
                pipeline = yaml.safe_load(generate_for_repository(root, str(config)))
            text = str(pipeline)
            self.assertIn("-p 9091:9090", text)
            self.assertIn("--platform linux/amd64", text)

    def test_invalid_ports_and_health_url_are_rejected(self):
        from backend.deployment_generator import generate_deployment_steps

        for options in [
            {"host_port": 0},
            {"container_port": 65536},
            {"health_check_url": "file:///tmp/check"},
        ]:
            with self.assertRaises(ValueError):
                generate_deployment_steps("linux-container", "app", "build", **options)


class BuildStrategyRegressionTest(unittest.TestCase):
    def test_dockerfile_build_publishes_image_without_railpack(self):
        from unittest.mock import patch
        import yaml
        from backend.pipeline_orchestrator import generate_for_discovered_repository

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").write_text("FROM scratch\nEXPOSE 5000\n")
            with patch(
                "backend.pipeline_orchestrator.generate_railpack_plan"
            ) as railpack:
                result = yaml.safe_load(
                    generate_for_discovered_repository(
                        root,
                        "docker-app",
                        deployment_target="linux-container",
                        build_platform="linux/amd64",
                        host_port=5001,
                    )
                )
            railpack.assert_not_called()
            steps = result["jobs"][0]["steps"]
            self.assertTrue(
                any("docker build --tag" in s.get("script", "") for s in steps)
            )
            self.assertTrue(any("docker save" in s.get("script", "") for s in steps))
            self.assertTrue(
                any(s.get("task") == "PublishPipelineArtifact@1" for s in steps)
            )
            self.assertIn("-p 5001:5000", str(result["jobs"][1]))

    def test_spring_gradle_keeps_railpack_and_jar_adapter(self):
        from unittest.mock import patch
        import yaml
        from backend.pipeline_orchestrator import generate_for_discovered_repository

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build.gradle").write_text(
                "java { toolchain { languageVersion = JavaLanguageVersion.of(17) } }"
            )
            resources = root / "src/main/resources"
            resources.mkdir(parents=True)
            (resources / "application.properties").write_text(
                "spring.application.name=petclinic\n"
            )
            with patch(
                "backend.pipeline_orchestrator.generate_railpack_plan",
                return_value={
                    "steps": [{"name": "build"}],
                    "deploy": {"startCommand": "java -jar */build/libs/*jar"},
                },
            ) as railpack:
                result = yaml.safe_load(
                    generate_for_discovered_repository(
                        root,
                        "spring-petclinic",
                        deployment_target="linux-container",
                    )
                )
            self.assertEqual(
                railpack.call_args.kwargs["build_variables"],
                {"RAILPACK_JDK_VERSION": "17"},
            )
            self.assertIn("railpack build", str(result))
            self.assertIn("-plain.jar", str(result))
            self.assertIn("-e PORT=8080", str(result))
            self.assertIn("-p 8082:8080", str(result))

    def test_incompatible_target_and_missing_project_fail(self):
        from backend.build_strategy_resolver import resolve_build_strategy

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                resolve_build_strategy("iis", root)
            (root / "package.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, ".NET publish"):
                resolve_build_strategy("iis", root)
            with self.assertRaises(ValueError):
                resolve_build_strategy("linux-container", root, "dotnet")
            (root / "App.csproj").write_text("<Project />")
            self.assertEqual(
                resolve_build_strategy("iis", root)["build_engine"], "dotnet"
            )
            self.assertEqual(
                resolve_build_strategy("linux-container", root)["build_engine"],
                "railpack",
            )

    def test_explicit_railpack_can_override_dockerfile(self):
        from backend.build_strategy_resolver import resolve_build_strategy

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").write_text("FROM scratch")
            (root / "package.json").write_text("{}")
            self.assertEqual(
                resolve_build_strategy("linux-container", root)["build_engine"],
                "dockerfile",
            )
            self.assertEqual(
                resolve_build_strategy("linux-container", root, "railpack")[
                    "build_engine"
                ],
                "railpack",
            )

    def test_invalid_railpack_plan_is_error_not_unchanged_skip(self):
        from unittest.mock import patch
        from backend.pipeline_orchestrator import generate_for_discovered_repository

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{}")
            with patch(
                "backend.pipeline_orchestrator.generate_railpack_plan", return_value={}
            ):
                with self.assertRaisesRegex(ValueError, "Railpack build planı"):
                    generate_for_discovered_repository(
                        root,
                        "app",
                        deployment_target="linux-container",
                        container_port=8080,
                    )

    def test_port_evidence_and_ambiguity(self):
        from backend.port_resolver import resolve_container_port

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").write_text(
                "FROM base AS build\nEXPOSE 3000\nFROM runtime\nEXPOSE 9000/tcp\n"
            )
            self.assertEqual(resolve_container_port(root), 9000)
            (root / "Dockerfile").write_text("FROM base\nEXPOSE 8000 9000\n")
            self.assertIsNone(resolve_container_port(root))
            (root / "Dockerfile").unlink()
            resources = root / "src/main/resources"
            resources.mkdir(parents=True)
            (resources / "application.yml").write_text(
                "server:\n  port: ${PORT:8090}\n"
            )
            self.assertEqual(resolve_container_port(root), 8090)


class ApiAndPrRegressionTest(unittest.TestCase):
    def test_preview_clones_selected_branch_and_uses_same_trigger(self):
        from unittest.mock import patch
        from subprocess import CompletedProcess
        import yaml
        from backend.main import PipelineRequest, preview_pipeline

        def clone(command, **kwargs):
            self.assertEqual(command[command.index("--branch") + 1], "release/demo")
            root = Path(command[-1])
            root.mkdir()
            (root / "Dockerfile").write_text("FROM scratch\nEXPOSE 8080\n")
            return CompletedProcess(command, 0)

        request = PipelineRequest(
            repository_url="https://github.com/example/app",
            deployment_target="linux-container",
            default_branch="release/demo",
            host_port=9001,
            health_check_url="http://localhost:9001/health",
        )
        with patch("backend.main.subprocess.run", side_effect=clone):
            result = preview_pipeline(request)
        self.assertEqual(result["status"], "PREVIEW_READY")
        self.assertEqual(yaml.safe_load(result["yaml"])["trigger"], ["release/demo"])
        self.assertIn("http://localhost:9001/health", result["yaml"])

    def test_existing_react_payload_and_analyzer_contract(self):
        from unittest.mock import patch
        from backend.main import PipelineRequest, RepositoryRequest, analyze_repository

        request = PipelineRequest(
            repository_url="https://github.com/example/app",
            deployment_target="linux-container",
            container_port=8080,
        )
        self.assertEqual(request.default_branch, "main")
        self.assertIsNone(request.build_engine)
        data = {
            "files": ["main.py"],
            "build_analysis": [],
            "language_analysis": {"languages": ["Python"]},
            "package_manager_analysis": [],
        }
        with patch("backend.main.clone_repository", return_value=data):
            result = analyze_repository(
                RepositoryRequest(repo_url=request.repository_url)
            )
        self.assertEqual(result["file_count"], 1)
        for field in data:
            self.assertEqual(result[field], data[field])

    def test_pr_dry_run_diff_skip_and_selected_branch(self):
        from unittest.mock import Mock, patch
        from backend.pipeline_deployer import deploy_repository_pipeline

        options = dict(
            repository_url="https://dev.azure.com/org/project/_git/app",
            repository_name="app",
            project_name="project",
            default_branch="release/demo",
            deployment_target="linux-container",
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").write_text("FROM scratch\nEXPOSE 8080\n")
            with patch(
                "backend.pipeline_deployer.clone_repository",
                return_value=(Mock(), root),
            ) as clone, patch(
                "backend.pipeline_deployer.prepare_deployment_branch"
            ) as branch:
                created = deploy_repository_pipeline(**options)
                self.assertEqual(created["status"], "DRY_RUN")
                self.assertEqual(created["decision"], "CREATE")
                self.assertIn("release/demo", created["diff"])
                from backend.pipeline_orchestrator import (
                    generate_for_discovered_repository,
                )

                generated = generate_for_discovered_repository(
                    root,
                    "app",
                    deployment_target="linux-container",
                    branch="release/demo",
                )
                (root / "azure-pipelines.generated.yml").write_text(generated)
                unchanged = deploy_repository_pipeline(**options)
                self.assertEqual(unchanged["status"], "SKIP")
                (root / "azure-pipelines.generated.yml").write_text("trigger: [old]\n")
                updated = deploy_repository_pipeline(**options)
                self.assertEqual(updated["decision"], "UPDATE")
                self.assertIn("-trigger: [old]", updated["diff"])
                branch.assert_not_called()
                self.assertEqual(clone.call_args.kwargs["branch"], "release/demo")

    def test_pr_commit_push_and_existing_pr_reuse_without_external_calls(self):
        from unittest.mock import Mock, patch
        from subprocess import CompletedProcess
        from backend.pipeline_deployer import deploy_repository_pipeline
        from backend.azure_devops_service import ensure_pull_request

        pr = {"pullRequestId": 8}
        with patch(
            "backend.azure_devops_service.find_existing_pull_request", return_value=pr
        ), patch("backend.azure_devops_service.create_pull_request") as create:
            self.assertEqual(
                ensure_pull_request("project", "app", "automation/pipeline-update"), pr
            )
            create.assert_not_called()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").write_text("FROM scratch\nEXPOSE 8080\n")
            with patch(
                "backend.pipeline_deployer.clone_repository",
                return_value=(Mock(), root),
            ), patch("backend.pipeline_deployer.prepare_deployment_branch"), patch(
                "backend.pipeline_deployer.commit_pipeline_yaml"
            ) as commit, patch(
                "backend.pipeline_deployer.push_pipeline_branch"
            ) as push, patch(
                "backend.pipeline_deployer.ensure_pull_request", return_value=pr
            ) as ensure, patch(
                "backend.pipeline_deployer.subprocess.run",
                side_effect=[
                    CompletedProcess([], 0, "", ""),
                    CompletedProcess([], 0, "", ""),
                    CompletedProcess([], 1, "", ""),
                ],
            ):
                result = deploy_repository_pipeline(
                    "https://dev.azure.com/org/project/_git/app",
                    "app",
                    "project",
                    dry_run=False,
                    default_branch="release/demo",
                    deployment_target="linux-container",
                )
            self.assertEqual(result["status"], "PR_READY")
            self.assertEqual(result["pull_request_id"], 8)
            commit.assert_called_once()
            push.assert_called_once()
            self.assertEqual(ensure.call_args.kwargs["target_branch"], "release/demo")
            self.assertIn("release/demo", commit.call_args.args[1])

    def test_api_keeps_real_pr_confirmation_guard(self):
        from fastapi import HTTPException
        from unittest.mock import patch
        from backend.main import PullRequestRequest, create_pipeline_pr

        request = PullRequestRequest(
            repository_url="https://dev.azure.com/org/project/_git/app",
            repository_name="app",
            project_name="project",
            deployment_target="linux-container",
            dry_run=False,
            confirmed=False,
        )
        with patch("backend.main.deploy_repository_pipeline") as deploy:
            with self.assertRaises(HTTPException) as error:
                create_pipeline_pr(request)
            self.assertEqual(error.exception.status_code, 400)
            deploy.assert_not_called()


class FinalEvidenceRegressionTest(unittest.TestCase):
    def test_commented_runtime_is_not_a_dependency(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
            )
            (root / "requirements.txt").write_text("# uvicorn\nfastapi\n")
            (root / "pyproject.toml").write_text(
                '[dependency-groups]\ndev = ["uvicorn"]\n'
            )
            with self.assertRaisesRegex(ValueError, "uvicorn"):
                adapt_start_command("python main.py", root)
            (root / "pyproject.toml").write_text(
                '[project]\ndependencies = ["fastapi", "uvicorn>=0.30"]\n'
            )
            self.assertIn("main:app", adapt_start_command("python main.py", root))

    def test_explicit_railpack_ignores_dockerfile_port(self):
        from unittest.mock import patch
        from backend.pipeline_orchestrator import generate_for_discovered_repository

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").write_text("FROM scratch\nEXPOSE 9000\n")
            (root / "pom.xml").write_text("<project />")
            resources = root / "src/main/resources"
            resources.mkdir(parents=True)
            (resources / "application.properties").write_text("server.port=8080")
            with patch(
                "backend.pipeline_orchestrator.generate_railpack_plan",
                return_value={
                    "steps": [{"name": "build"}],
                    "deploy": {"startCommand": "java -jar app.jar"},
                },
            ):
                result = generate_for_discovered_repository(
                    root,
                    "app",
                    deployment_target="linux-container",
                    build_engine="railpack",
                )
            self.assertIn("8082:8080", result)
            self.assertNotIn("8082:9000", result)

    def test_generated_container_scripts_have_valid_shell_syntax(self):
        import subprocess
        from backend.deployment_generator import generate_deployment_steps
        from backend.railpack_ci_generator import (
            generate_docker_ci_steps,
            generate_railpack_ci_steps,
        )

        steps = generate_deployment_steps(
            "linux-container",
            "petclinic",
            "build",
            health_check_url="http://localhost:8080/health",
        )
        steps += generate_docker_ci_steps(
            "$(Build.SourcesDirectory)", "build", "linux/amd64"
        )
        steps += generate_railpack_ci_steps(
            "railpack build . --name autopipeline-build",
            "$(Build.SourcesDirectory)",
            "build",
        )
        for step in steps:
            if "script" in step:
                check = subprocess.run(
                    ["bash", "-n"], input=step["script"], text=True, capture_output=True
                )
                self.assertEqual(check.returncode, 0, check.stderr)


class PythonEntrypointRegressionTest(unittest.TestCase):
    def test_top_level_uvicorn_entrypoint_is_preserved(self):
        for runtime in [
            "import uvicorn as server\nserver.run(app)",
            "from uvicorn import run as serve\nserve(app)",
        ]:
            with TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "main.py").write_text(
                    "from fastapi import FastAPI\napp = FastAPI()\n" + runtime
                )
                self.assertEqual(
                    adapt_start_command("python main.py", root), "python main.py"
                )

    def test_similarly_named_package_is_not_uvicorn(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
            )
            (root / "requirements.txt").write_text("uvicorn-worker\nfastapi\n")
            with self.assertRaisesRegex(ValueError, "uvicorn"):
                adapt_start_command("python main.py", root)


class DockerArchitectureRegressionTest(unittest.TestCase):

    def test_arm64_prepares_buildx_and_qemu(self):
        from backend.railpack_ci_generator import generate_docker_ci_steps

        steps = generate_docker_ci_steps(
            "$(Build.SourcesDirectory)",
            "application-build",
            build_platform="linux/arm64",
        )

        scripts = "\n".join(step.get("script", "") for step in steps)

        self.assertIn("tonistiigi/binfmt --install arm64", scripts)
        self.assertIn("docker buildx inspect --bootstrap", scripts)
        self.assertIn("docker buildx build --platform linux/arm64", scripts)
        self.assertIn("--load .", scripts)
        self.assertIn("docker save autopipeline-build:latest", scripts)

    def test_amd64_preserves_existing_build(self):
        from backend.railpack_ci_generator import generate_docker_ci_steps

        steps = generate_docker_ci_steps(
            "$(Build.SourcesDirectory)",
            "application-build",
            build_platform="linux/amd64",
        )

        scripts = "\n".join(step.get("script", "") for step in steps)

        self.assertIn(
            "docker build --tag autopipeline-build:latest --platform linux/amd64 .",
            scripts,
        )
        self.assertNotIn("tonistiigi/binfmt", scripts)
