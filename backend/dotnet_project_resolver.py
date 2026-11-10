"""Read .NET build evidence without executing repository/MSBuild code."""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.build_detector import find_build_files


IGNORED = {'bin', 'obj', '.git', 'node_modules', '.venv', 'venv'}


def _xml(path: Path):
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as error:
        raise ValueError(f'.NET proje XML okunamadı: {path.name}') from error
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    return root


def _properties(path: Path, scope: Path) -> tuple[dict, object]:
    properties = {"MSBuildProjectName": path.stem}
    directories = []
    directory = path.parent
    while directory.is_relative_to(scope):
        directories.append(directory)
        if directory == scope:
            break
        directory = directory.parent
    # MSBuild automatically imports only the nearest Directory.Build.props.
    props = next((d / 'Directory.Build.props' for d in directories
                  if (d / 'Directory.Build.props').is_file()), None)
    if props and not props.resolve().is_relative_to(scope):
        raise ValueError("Directory.Build.props repository dışında olamaz.")
    project = _xml(path)
    for root in ([_xml(props)] if props else []) + [project]:
        for group in root.findall('PropertyGroup'):
            if group.get('Condition'):
                continue
            for node in group:
                if not node.get('Condition') and node.text:
                    value = node.text.strip()
                    for name, previous in properties.items():
                        value = value.replace(f'$({name})', previous)
                    properties[node.tag] = value
    return properties, project


def _is_test(properties: dict, project) -> bool:
    return properties.get('IsTestProject', '').lower() == 'true' or any(
        node.get('Include', '').lower() == 'microsoft.net.test.sdk'
        for node in project.iter('PackageReference')
    )


def _service_entrypoint(project: Path) -> bool:
    for source in project.parent.rglob('*'):
        if source.suffix not in {'.cs', '.fs'} or any(part in IGNORED for part in source.relative_to(project.parent).parts):
            continue
        # Don't borrow hosting evidence from another nested project.
        parent = source.parent
        while parent != project.parent and not any(parent.glob('*.*proj')):
            parent = parent.parent
        if parent != project.parent or not source.resolve().is_relative_to(project.parent.resolve()):
            continue
        content = source.read_text(encoding='utf-8', errors='replace')
        content = re.sub(r'/\*.*?\*/|//[^\n]*', '', content, flags=re.DOTALL)
        if re.search(r'\b(?:UseWindowsService|AddWindowsService)\s*\(', content) or re.search(r'\bServiceBase\s*\.\s*Run\s*\(', content):
            return True
    return False


def resolve_dotnet_project(repository_path: Path, project_directory: Path, target: str | None, config: dict) -> dict:
    repository_path = repository_path.resolve()
    project_directory = project_directory.resolve()
    projects = find_build_files(project_directory, ['*.csproj', '*.fsproj'])
    projects = [p for p in projects if not any(part in IGNORED for part in p.relative_to(project_directory).parts)]
    evidence = {}
    for project in projects:
        if not project.resolve().is_relative_to(repository_path):
            raise ValueError('.NET projesi repository dışında olamaz.')
        evidence[project] = _properties(project, repository_path)

    selected = config.get('dotnet_project')
    if selected:
        if not isinstance(selected, str) or '\\' in selected:
            raise ValueError('dotnet_project repository içi proje yolu olmalıdır.')
        candidate = (project_directory / selected).resolve()
        if not candidate.is_relative_to(project_directory) or candidate not in evidence:
            raise ValueError('dotnet_project geçerli bir .csproj/.fsproj olmalıdır.')
        candidates = [candidate]
    else:
        candidates = []
        for project, (properties, tree) in evidence.items():
            sdk = tree.get('Sdk', '')
            web = 'Microsoft.NET.Sdk.Web' in sdk or any(
                node.get('Include') == 'Microsoft.AspNetCore.App' for node in tree.iter('FrameworkReference')
            )
            executable = web or 'Microsoft.NET.Sdk.Worker' in sdk or properties.get('OutputType', '').lower() in {'exe', 'winexe'}
            if _is_test(properties, tree):
                continue
            if (target == 'iis' and web) or (target == 'windows-service' and executable and _service_entrypoint(project)) or (target is None and executable):
                candidates.append(project)
    if len(candidates) != 1:
        raise ValueError('Tek bir yayınlanabilir .NET projesi belirlenemedi; dotnet_project belirtin.')
    project = candidates[0]
    properties, tree = evidence[project]
    if _is_test(properties, tree):
        raise ValueError('Test projesi publish edilemez.')
    sdk = tree.get('Sdk', '')
    web = 'Microsoft.NET.Sdk.Web' in sdk or any(node.get('Include') == 'Microsoft.AspNetCore.App' for node in tree.iter('FrameworkReference'))
    if not sdk and not tree.findall('Sdk'):
        raise ValueError('SDK tabanlı .NET projesi gerekli.')
    if properties.get('PublishAot', '').lower() == 'true':
        raise ValueError('Native AOT publish bu deployment akışında desteklenmiyor.')
    if target == 'iis' and not web:
        raise ValueError('IIS için ASP.NET Core Web projesi gerekli.')
    if target == 'windows-service' and not _service_entrypoint(project):
        raise ValueError('Windows Service için UseWindowsService/AddWindowsService veya ServiceBase.Run kanıtı gerekli.')

    declared = properties.get('TargetFramework', properties.get('TargetFrameworks', ''))
    frameworks = [value.strip() for value in declared.split(';') if value.strip()]
    framework = config.get('dotnet_framework')
    if framework:
        if frameworks and '$(' not in declared and framework not in frameworks:
            raise ValueError('dotnet_framework proje hedefleriyle uyuşmuyor.')
    elif len(frameworks) == 1:
        framework = frameworks[0]
    else:
        raise ValueError('TargetFramework belirsiz; dotnet_framework belirtin.')
    match = re.fullmatch(r'net(\d+)\.(\d+)(?:-windows[\d.]*)?', framework)
    if not match or int(match.group(1)) < 5:
        raise ValueError('Yalnızca SDK tabanlı modern .NET hedefleri destekleniyor; dotnet_framework belirtin.')

    required_sdk = (int(match.group(1)), int(match.group(2)))
    for props, xml in evidence.values():
        if _is_test(props, xml):
            for test_framework in props.get('TargetFramework', props.get('TargetFrameworks', '')).split(';'):
                test_match = re.fullmatch(r'net(\d+)\.(\d+)(?:-windows[\d.]*)?', test_framework.strip())
                if test_match:
                    required_sdk = max(required_sdk, (int(test_match.group(1)), int(test_match.group(2))))
    global_json = None
    directory = project.parent
    while directory.is_relative_to(repository_path):
        if (directory / 'global.json').is_file():
            global_json = directory / 'global.json'
            break
        if directory == repository_path:
            break
        directory = directory.parent
    sdk_version = config.get('dotnet_sdk_version')
    if global_json:
        if not global_json.resolve().is_relative_to(repository_path):
            raise ValueError('global.json repository dışında olamaz.')
        try:
            sdk_version_from_file = json.loads(global_json.read_text(encoding='utf-8-sig'))['sdk']['version']
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError('global.json geçerli bir sdk.version içermelidir.') from error
        if not isinstance(sdk_version_from_file, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[\w.-]+)?', sdk_version_from_file):
            raise ValueError('global.json SDK sürümü tam sürüm olmalıdır.')
        if sdk_version and sdk_version != sdk_version_from_file:
            raise ValueError('dotnet_sdk_version global.json ile çelişiyor.')
        sdk_version = sdk_version_from_file
    sdk_version = sdk_version or f'{required_sdk[0]}.{required_sdk[1]}.x'
    if not isinstance(sdk_version, str) or not re.fullmatch(r'\d+\.\d+\.(?:x|\d+(?:-[\w.-]+)?)', sdk_version):
        raise ValueError('Geçersiz dotnet_sdk_version.')
    if tuple(map(int, sdk_version.split('.')[:2])) < required_sdk:
        raise ValueError('.NET SDK sürümü uygulama/test TargetFramework için yetersiz.')

    runtime = config.get('dotnet_runtime') or 'win-x64'
    if runtime not in {'win-x64', 'win-x86', 'win-arm64'} or (target == 'iis' and runtime == 'win-arm64'):
        raise ValueError('Desteklenmeyen Windows dotnet_runtime.')
    assembly = properties.get('AssemblyName', project.stem)
    if not assembly or assembly in {'.', '..'} or re.search(r'[<>:"/\\|?*\x00-\x1f]|\$\(', assembly) or assembly.endswith((' ', '.')):
        raise ValueError('AssemblyName güvenli bir Windows dosya adı olmalıdır.')
    self_contained = config.get('dotnet_self_contained')
    if self_contained is None:
        self_contained = False
    if type(self_contained) is not bool:
        raise ValueError('dotnet_self_contained boolean olmalıdır.')
    return {
        'dotnet_project': project.relative_to(repository_path).as_posix(),
        'dotnet_working_directory': project.parent.relative_to(repository_path).as_posix(),
        'dotnet_sdk_version': sdk_version,
        'dotnet_global_json': global_json.relative_to(repository_path).as_posix() if global_json else None,
        'dotnet_framework': framework,
        'dotnet_runtime': runtime,
        'dotnet_self_contained': self_contained,
        'dotnet_use_apphost': target != 'iis' or self_contained,
        'dotnet_assembly_name': assembly,
        'dotnet_test_projects': sorted(p.relative_to(repository_path).as_posix()
                                       for p, (props, xml) in evidence.items() if _is_test(props, xml)),
    }
