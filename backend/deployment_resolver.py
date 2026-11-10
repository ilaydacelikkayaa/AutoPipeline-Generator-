DEPLOYMENT_ENVIRONMENTS = {
    "linux-container": {
        "agent_pool": "AutoPipeline-Linux",
        "build_platform": "linux/arm64",
        "host_port": 8082,
    },
    "iis": {
        "agent_pool": "AutoPipeline-Windows",
    },
    "windows-service": {
        "agent_pool": "AutoPipeline-Windows",
    },
}


def resolve_deployment(deployment_target, agent_pool=None, host_port=None, build_platform=None):
    if deployment_target is None:
        return {
            "deployment_target": None,
            "agent_pool": None,
        }

    environment = DEPLOYMENT_ENVIRONMENTS.get(deployment_target)

    if environment is None:
        raise ValueError(f"Deployment ortamı tanımlanmamış: {deployment_target}")

    return {
        "deployment_target": deployment_target,
        "agent_pool": agent_pool or environment["agent_pool"],
        "build_platform": build_platform if build_platform is not None else environment.get("build_platform"),
        "host_port": host_port if host_port is not None else environment.get("host_port"),
    }
