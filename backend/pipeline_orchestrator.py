from pathlib import Path

from backend.config_loader import load_pipeline_config
from backend.runtime_resolver import resolve_runtime_variables
from backend.railpack_service import generate_railpack_plan
from backend.pipeline_plan import create_pipeline_plan
from backend.yaml_generator import generate_pipeline_yaml, validate_project_path
from backend.port_resolver import resolve_container_port, resolve_spring_boot_port
from backend.deployment_resolver import resolve_deployment
from backend.build_strategy_resolver import resolve_build_strategy
from backend.dotnet_project_resolver import resolve_dotnet_project


def _generate_pipeline(repository_path: Path, config: dict) -> str:
    repository_path = repository_path.resolve()
    if not repository_path.is_dir():
        raise ValueError('Repository klasörü bulunamadı.')
    project_path = validate_project_path(config.get('project_path', '.'))
    project_directory = (repository_path / project_path).resolve()
    if not project_directory.is_relative_to(repository_path):
        raise ValueError('Proje yolu repository dışına çıkamaz.')
    if not project_directory.is_dir():
        raise ValueError('Proje klasörü bulunamadı.')

    target = config.get('deployment_target')
    fields = {
        'iis': ('app_pool_name', 'site_path', 'health_check_url'),
        'windows-service': ('service_name', 'install_path'),
    }
    missing = [name for name in fields.get(target, ())
               if not isinstance(config.get(name), str) or not config[name].strip()]
    if missing:
        raise ValueError(f'{target} deployment için eksik bilgiler: {", ".join(missing)}')

    strategy = resolve_build_strategy(target, project_directory, config.get('build_engine'))
    engine = strategy['build_engine']
    pipeline_plan = {'project_path': project_path}
    container_port = config.get('container_port')
    if container_port is None and engine != 'dotnet':
        container_port = (resolve_container_port(project_directory) if engine == "dockerfile"
                          else resolve_spring_boot_port(project_directory))
    if engine == 'railpack':
        runtime_variables = resolve_runtime_variables(project_directory)
        railpack_plan = generate_railpack_plan(project_directory, build_variables=runtime_variables)
        if not railpack_plan.get('steps'):
            raise ValueError('Railpack build planı oluşturamadı.')
        pipeline_plan = create_pipeline_plan(
            railpack_plan, project_path,
            repository_directory=project_directory,
            runtime_variables=runtime_variables,
            container_port=container_port,
        )
    pipeline_plan.update({key: value for key, value in config.items() if value is not None})
    pipeline_plan.update(strategy)
    if engine == "dotnet":
        pipeline_plan.update(resolve_dotnet_project(repository_path, project_directory, target, config))
        pipeline_plan["vm_image"] = config.get("vm_image") or "windows-latest"
    pipeline_plan['container_port'] = container_port
    pipeline_plan.update(resolve_deployment(
        target, agent_pool=config.get('agent_pool'),
        host_port=config.get('host_port'), build_platform=config.get('build_platform'),
    ))
    if target == 'linux-container' and container_port is None:
        raise ValueError('Linux Container için container_port belirlenemedi.')
    return generate_pipeline_yaml(pipeline_plan)


def generate_for_repository(
    repository_path: Path,
    config_path: str = 'config.yaml',
) -> str:
    return _generate_pipeline(repository_path, load_pipeline_config(config_path))


def generate_for_discovered_repository(
    repository_path: Path,
    repository_name: str,
    deployment_target: str | None = None,
    agent_pool: str | None = None,
    app_pool_name: str | None = None,
    site_path: str | None = None,
    health_check_url: str | None = None,
    service_name: str | None = None,
    install_path: str | None = None,
    container_port: int | None = None,
    host_port: int | None = None,
    build_platform: str | None = None,
    build_engine: str | None = None,
    branch: str = 'main',
    dotnet_project: str | None = None,
    dotnet_framework: str | None = None,
    dotnet_sdk_version: str | None = None,
    dotnet_runtime: str | None = None,
    dotnet_self_contained: bool | None = None,
    agent_name: str | None = None,
) -> str:
    return _generate_pipeline(repository_path, {
        'project_path': '.', 'project_name': repository_name,
        'branch': branch,
        'artifact_name': 'application-build',
        'deployment_target': deployment_target, 'agent_pool': agent_pool,
        'app_pool_name': app_pool_name, 'site_path': site_path,
        'health_check_url': health_check_url,
        'service_name': service_name, 'install_path': install_path,
        'container_port': container_port, 'host_port': host_port,
        'build_platform': build_platform, 'build_engine': build_engine,
        'dotnet_project': dotnet_project,
        'dotnet_framework': dotnet_framework,
        'dotnet_sdk_version': dotnet_sdk_version,
        'dotnet_runtime': dotnet_runtime,
        'dotnet_self_contained': dotnet_self_contained,
        'agent_name': agent_name,
    })
