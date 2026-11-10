import yaml

SUPPORTED_DEPLOYMENT_TARGETS = {
    "linux-container",
    "iis",
    "windows-service",
}


def load_pipeline_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("Config dosyası geçerli bir YAML nesnesi olmalıdır.")

    project = config.get("project", {})
    pipeline = config.get("pipeline", {})
    artifact = config.get("artifact", {})
    deployment = config.get("deployment", {})

    if not isinstance(deployment, dict):
        raise ValueError("Deployment ayarları YAML nesnesi olmalıdır.")

    deployment_target = deployment.get("target")

    if (
        deployment_target is not None
        and deployment_target not in SUPPORTED_DEPLOYMENT_TARGETS
    ):
        raise ValueError(f"Desteklenmeyen deployment hedefi: {deployment_target}")

    return {
        "project_name": project.get("name"),
        "project_path": project.get("path", "."),
        "branch": project.get("branch", "main"),
        "vm_image": pipeline.get("vm_image"),
        "build_engine": pipeline.get("build_engine"),
        "execution_mode": pipeline.get("execution_mode", "container"),
        "artifact_name": artifact.get("name", "application-build"),
        "deployment_target": deployment_target,
        "deployment_environment": deployment.get("environment", "staging"),
        "agent_pool": deployment.get("agent_pool"),
        "app_pool_name": deployment.get("app_pool_name"),
        "site_path": deployment.get("site_path"),
        "health_check_url": deployment.get("health_check_url"),
        "service_name": deployment.get("service_name"),
        "install_path": deployment.get("install_path"),
        "container_port": deployment.get("container_port"),
        "host_port": deployment.get("host_port"),
        "build_platform": pipeline.get("build_platform"),
        "dotnet_project": pipeline.get("dotnet_project"),
        "dotnet_framework": pipeline.get("dotnet_framework"),
        "dotnet_sdk_version": pipeline.get("dotnet_sdk_version"),
        "dotnet_runtime": pipeline.get("dotnet_runtime"),
        "dotnet_self_contained": pipeline.get("dotnet_self_contained"),
        "agent_name": deployment.get("agent_name"),
    }
