import yaml
import shlex
from pathlib import PurePosixPath
from backend.deployment_generator import generate_deployment_job
from backend.dotnet_ci_generator import generate_dotnet_ci_steps
from backend.railpack_ci_generator import generate_railpack_ci_steps, generate_docker_ci_steps


def validate_project_path(project_path: str):
    if not isinstance(project_path, str):
        raise ValueError("Project path metin olmalıdır.")

    if project_path == ".":
        return "."

    if not project_path or "\\" in project_path:
        raise ValueError("Geçersiz proje yolu.")

    path = PurePosixPath(project_path)

    if path.is_absolute() or any(
        part in ("", ".", "..") for part in project_path.split("/")
    ):
        raise ValueError("Proje yolu repository içinde olmalıdır.")

    return project_path


def generate_pipeline_yaml(pipeline_plan: dict):
    project_path = validate_project_path(pipeline_plan["project_path"])
    artifact_name = pipeline_plan.get("artifact_name", "application-build")
    build_engine = pipeline_plan.get("build_engine", "railpack")
    deployment_target = pipeline_plan.get("deployment_target", None)
    uses_port_variable = pipeline_plan.get("uses_port_variable", False)
    runtime_variables = pipeline_plan.get("runtime_variables", {})
    repository_name = pipeline_plan.get("project_name")
    build_platform = pipeline_plan.get("build_platform")
    start_command = pipeline_plan.get("start_command")

    host_port = pipeline_plan.get("host_port")
    container_port = pipeline_plan.get("container_port")
    if deployment_target == "linux-container" and not repository_name:
        raise ValueError("Linux deployment için proje adı gerekli.")
    working_directory = "$(Build.SourcesDirectory)"

    if project_path != ".":
        working_directory += "/" + project_path

    if build_engine == "dotnet":
        ci_steps = generate_dotnet_ci_steps(artifact_name, pipeline_plan)
    elif build_engine == "dockerfile":
        ci_steps = generate_docker_ci_steps(working_directory, artifact_name, build_platform)
    elif build_engine == "railpack":
        build_command = "railpack build . --name autopipeline-build"

        if start_command:
            build_command += f" --start-cmd {shlex.quote(start_command)}"

        if build_platform:
            if build_platform not in ("linux/amd64", "linux/arm64"):
                raise ValueError(f"Desteklenmeyen platform: {build_platform}")

            build_command += f" --platform {build_platform}"

        for key, value in runtime_variables.items():
            if not key.startswith("RAILPACK_"):
                raise ValueError(f"Geçersiz Railpack ayarı: {key}")

            build_command += f" --env {key}={value}"

        ci_steps = generate_railpack_ci_steps(
            build_command, working_directory, artifact_name
        )
    else:
        raise ValueError(
            f"Unsupported build engine: '{build_engine}'. "
            "Supported engines: dotnet, railpack, dockerfile"
        )

    pipeline = {
        "trigger": [pipeline_plan.get("branch", "main")],
        "jobs": [
            {
                "job": "Build",
                "displayName": "Build Application",
                "pool": {"vmImage": pipeline_plan.get("vm_image", "ubuntu-latest")},
                "steps": ci_steps,
            }
        ],
    }
    deployment_job = generate_deployment_job(
        deployment_target,
        repository_name,
        artifact_name,
        uses_port_variable=uses_port_variable,
        host_port=host_port,
        container_port=container_port,
        agent_pool=pipeline_plan.get("agent_pool"),
        app_pool_name=pipeline_plan.get("app_pool_name"),
        site_path=pipeline_plan.get("site_path"),
        health_check_url=pipeline_plan.get("health_check_url"),
        service_name=pipeline_plan.get("service_name"),
        install_path=pipeline_plan.get("install_path"),
        assembly_name=pipeline_plan.get("dotnet_assembly_name"),
        dotnet_runtime=pipeline_plan.get("dotnet_runtime"),
        require_exe=pipeline_plan.get("dotnet_use_apphost", False),
        agent_name=pipeline_plan.get("agent_name"),
    )

    if deployment_job is not None:
        pipeline["jobs"].append(deployment_job)

    return yaml.safe_dump(pipeline, sort_keys=False)
