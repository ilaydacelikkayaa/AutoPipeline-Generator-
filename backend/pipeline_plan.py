import re

from backend.start_command_adapter import adapt_start_command


def extract_step_commands(railpack_plan: dict, step_name: str):
    result = []

    steps = railpack_plan.get("steps", [])

    for step in steps:
        if step.get("name") == step_name:
            commands = step.get("commands", [])

            for command in commands:
                cmd = command.get("cmd")

                if cmd:
                    result.append(cmd)

    return result


def create_pipeline_plan(
    railpack_plan,
    project_path,
    runtime_variables=None,
    host_port=None,
    container_port=None,
    repository_directory=None,
):
    install_commands = extract_step_commands(railpack_plan, "install")
    build_commands = extract_step_commands(railpack_plan, "build")

    all_commands = install_commands + build_commands
    command_checks = inspect_commands(all_commands)
    start_command = adapt_start_command(
        (railpack_plan.get("deploy") or {}).get("startCommand"),
        repository_directory if repository_directory is not None else project_path,
    )
    pipeline_plan = {
        "project_path": project_path,
        "build_engine": "railpack",
        "execution_mode": "container",
        "install_commands": install_commands,
        "build_commands": build_commands,
        "runtime_variables": runtime_variables or {},
        "command_checks": command_checks,
        "status": "needs_validation",
        "uses_port_variable": uses_port_variable({"deploy": {"startCommand": start_command}}),
        "host_port": host_port,
        "container_port": container_port,
        "start_command": start_command,
    }

    return pipeline_plan


def inspect_commands(commands: list[str]):
    results = []

    for command in commands:
        if "/app/" in command:
            status = "needs_review"
            reason = "Komut Railpack container yoluna bağlı olabilir."
        else:
            status = "unverified"
            reason = "Komut henüz Azure DevOps ortamında doğrulanmadı."

        results.append({"command": command, "status": status, "reason": reason})

    return results


def uses_port_variable(railpack_plan: dict) -> bool:
    deploy = railpack_plan.get("deploy") or {}
    start_command = deploy.get("startCommand") or ""

    return bool(re.search(r"\$PORT\b|\$\{PORT(?=[:}])", start_command))
