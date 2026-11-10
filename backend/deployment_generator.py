import re
from urllib.parse import urlparse
from backend.artifact_download_generator import generate_artifact_download_step
from backend.iis_deployment_generator import generate_iis_deployment_steps
from backend.windows_service_deployment_generator import (
    generate_windows_service_deployment_steps,
)


def normalize_container_name(repository_name):
    if not isinstance(repository_name, str) or not repository_name.strip():
        raise ValueError("Geçerli bir repository adı gerekli.")

    name = repository_name.lower().strip()
    name = re.sub(r"[^a-z0-9_.-]+", "-", name)
    name = name.strip("-._")

    if not name:
        raise ValueError("Geçerli bir container adı oluşturulamadı.")

    return name


def generate_deployment_steps(
    deployment_target,
    container_name,
    artifact_name,
    host_port=8080,
    container_port=8080,
    uses_port_variable=False,
    app_pool_name=None,
    site_path=None,
    health_check_url=None,
    service_name=None,
    install_path=None,
    assembly_name=None,
    dotnet_runtime=None,
    require_exe=False,
):

    if deployment_target is None:
        return []

    if deployment_target == "linux-container":
        if host_port is None or container_port is None:
            raise ValueError(
                "Linux deployment için host_port ve container_port gerekli."
            )
        for port in (host_port, container_port):
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("Port 1 ile 65535 arasında tam sayı olmalı.")
        port_env = ""
        if uses_port_variable:
            port_env = f"-e PORT={container_port}"
        health_check_url = health_check_url or f"http://localhost:{host_port}/"
        parsed = urlparse(health_check_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Health check için HTTP veya HTTPS URL gerekli.")
        return [
            generate_artifact_download_step(artifact_name),
            {
                "script": (
                    "docker load -i " "$(Pipeline.Workspace)/downloaded/application.tar"
                ),
                "displayName": "Load Docker Image",
            },
            {
                "script": f"docker rm -f {container_name} || true",
                "displayName": "Remove Previous Container",
            },
            {
                "script": f"docker run -d --name {container_name} {port_env} -p {host_port}:{container_port} autopipeline-build:latest",
                "displayName": "Run Docker Container",
            },
            {
                "script": (
                    "set -eu\n"
                    f"container_name='{container_name}'\n"
                    "sleep 10\n"
                    "if [ \"$(docker inspect -f '{{.State.Running}}' \"$container_name\")\" != 'true' ]; then\n"
                    "  echo 'ERROR: Container stopped after deployment.'\n"
                    '  docker logs --tail 100 "$container_name" || true\n'
                    "  exit 1\n"
                    "fi\n"
                    "echo 'Container is running.'"
                ),
                "displayName": "Verify Container Running",
            },
            {
                "script": (
                    "set -eu\n"
                    "for attempt in $(seq 1 30); do\n"
                    '  status=$(curl -s -o /dev/null -w "%{http_code}" '
                    '--max-time 5 "$HEALTH_CHECK_URL" || true)\n'
                    '  if [ "$status" = "200" ]; then\n'
                    '    echo "HTTP health check passed."\n'
                    "    exit 0\n"
                    "  fi\n"
                    '  echo "Waiting for application... HTTP $status ($attempt/30)"\n'
                    "  sleep 5\n"
                    "done\n"
                    'echo "ERROR: Application health check failed."\n'
                    f"docker logs --tail 100 '{container_name}' || true\n"
                    "exit 1"
                ),
                "displayName": "HTTP Health Check",
                "env": {"HEALTH_CHECK_URL": health_check_url},
            },
        ]
    elif deployment_target == "iis":
        return [
            generate_artifact_download_step(artifact_name),
            *generate_iis_deployment_steps(
                artifact_name=artifact_name,
                app_pool_name=app_pool_name,
                site_path=site_path,
                health_check_url=health_check_url,
                assembly_name=assembly_name,
                dotnet_runtime=dotnet_runtime,
                require_exe=require_exe,
            ),
        ]
    elif deployment_target == "windows-service":
        return [
            generate_artifact_download_step(artifact_name),
            *generate_windows_service_deployment_steps(
                artifact_name=artifact_name,
                service_name=service_name,
                install_path=install_path,
                assembly_name=assembly_name,
                health_check_url=health_check_url,
                dotnet_runtime=dotnet_runtime,
            ),
        ]
    raise ValueError(f"Desteklenmeyen deployment hedefi: {deployment_target}")


def generate_deployment_job(
    deployment_target,
    container_name,
    artifact_name,
    uses_port_variable=False,
    host_port=None,
    container_port=None,
    agent_pool=None,
    app_pool_name=None,
    site_path=None,
    health_check_url=None,
    service_name=None,
    install_path=None,
    assembly_name=None,
    dotnet_runtime=None,
    require_exe=False,
    agent_name=None,
):
    if deployment_target is None:
        return None
    if not isinstance(agent_pool, str) or not agent_pool.strip():
        raise ValueError("Deployment için geçerli bir agent pool gerekli.")
    if deployment_target == "linux-container":
        container_name = normalize_container_name(container_name)
    deployment_steps = generate_deployment_steps(
        deployment_target,
        container_name,
        artifact_name,
        uses_port_variable=uses_port_variable,
        host_port=host_port,
        container_port=container_port,
        app_pool_name=app_pool_name,
        site_path=site_path,
        health_check_url=health_check_url,
        service_name=service_name,
        install_path=install_path,
        assembly_name=assembly_name,
        dotnet_runtime=dotnet_runtime,
        require_exe=require_exe,
    )

    pool_config = {"name": agent_pool}
    if deployment_target in {"iis", "windows-service"}:
        pool_config["demands"] = ["Agent.OS -equals Windows_NT"]
        if agent_name:
            if not isinstance(agent_name, str) or not agent_name.strip() or any(char in agent_name for char in "\r\n"):
                raise ValueError("Geçerli bir agent_name gerekli.")
            pool_config["demands"].append(f"Agent.Name -equals {agent_name}")
    deployment_job = {
        "job": "Deploy",
        "displayName": "Deploy Application",
        "dependsOn": "Build",
        "pool": pool_config,
        "steps": deployment_steps,
    }
    return deployment_job
