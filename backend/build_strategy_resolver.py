from pathlib import Path

from backend.build_detector import find_build_files
from backend.project_discovery import PROJECT_FILES


def resolve_build_strategy(
    deployment_target: str | None,
    repository_path: Path,
    build_engine: str | None = None,
) -> dict:
    if deployment_target not in {None, 'linux-container', 'iis', 'windows-service'}:
        raise ValueError(f'Unsupported deployment target: {deployment_target}')

    dotnet_projects = find_build_files(repository_path, ['*.csproj', '*.fsproj'])
    has_dockerfile = (repository_path / 'Dockerfile').is_file()
    has_manifest = any((repository_path / name).is_file() for name in PROJECT_FILES)

    if build_engine is None:
        if deployment_target in {'iis', 'windows-service'} and dotnet_projects:
            build_engine = 'dotnet'
        elif has_dockerfile:
            build_engine = 'dockerfile'
        elif has_manifest or dotnet_projects:
            build_engine = 'railpack'
        else:
            raise ValueError('Build stratejisi için Dockerfile veya proje manifesti bulunamadı.')

    if build_engine not in {'railpack', 'dockerfile', 'dotnet'}:
        raise ValueError(f'Desteklenmeyen build engine: {build_engine}')
    if build_engine == 'dockerfile' and not has_dockerfile:
        raise ValueError('Dockerfile build için Dockerfile gerekli.')
    if build_engine == 'dotnet' and not dotnet_projects:
        raise ValueError('.NET build için .csproj veya .fsproj gerekli.')
    if build_engine == 'railpack' and not (has_manifest or dotnet_projects):
        raise ValueError('Railpack build için proje manifesti gerekli.')
    artifact_type = 'publish-directory' if build_engine == 'dotnet' else 'docker-image'
    if deployment_target == 'linux-container' and artifact_type != 'docker-image':
        raise ValueError('Linux Container için Dockerfile veya Railpack image build gerekli.')
    if deployment_target in {'iis', 'windows-service'} and artifact_type != 'publish-directory':
        raise ValueError('IIS/Windows Service için .NET publish build gerekli.')
    return {'build_engine': build_engine, 'artifact_type': artifact_type}
