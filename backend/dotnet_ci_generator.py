from pathlib import PurePosixPath
from textwrap import dedent


def _source_path(path: str) -> str:
    return '$(Build.SourcesDirectory)' + ('/' + path if path != '.' else '')


def _quote(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def generate_dotnet_ci_steps(artifact_name: str, plan: dict) -> list:
    working_directory = _source_path(plan['dotnet_working_directory'])
    sdk_inputs = {'packageType': 'sdk'}
    if plan.get('dotnet_global_json'):
        sdk_inputs.update({
            'useGlobalJson': True,
            'workingDirectory': _source_path(str(PurePosixPath(plan['dotnet_global_json']).parent)),
        })
    else:
        sdk_inputs['version'] = plan['dotnet_sdk_version']
        if '-' in plan['dotnet_sdk_version']:
            sdk_inputs['includePreviewVersions'] = True
    runtime = plan['dotnet_runtime']
    framework = plan['dotnet_framework']
    properties = (
        f'-p:SelfContained={str(plan["dotnet_self_contained"]).lower()} '
        f'-p:UseAppHost={str(plan["dotnet_use_apphost"]).lower()} '
        '-p:PublishSingleFile=false'
    )
    project = _quote(_source_path(plan['dotnet_project']))
    build_arguments = f'{project} --configuration Release --framework {framework} --runtime {runtime} {properties}'

    def command(name, arguments, display_name):
        return {
            'task': 'DotNetCoreCLI@2', 'displayName': display_name,
            'inputs': {'command': 'custom', 'custom': name, 'arguments': arguments,
                       'workingDirectory': working_directory},
        }

    steps = [
        {'checkout': 'self'},
        {'task': 'UseDotNet@2', 'displayName': 'Prepare .NET SDK', 'inputs': sdk_inputs},
    ]
    # Test projects are built/restored separately for the build agent's native runtime.
    # They must never execute the Windows RID application output on a Linux agent.
    for test in plan.get('dotnet_test_projects', []):
        steps.append(command('test',
            f'{_quote(_source_path(test))} --configuration Release --logger trx '
            '--results-directory "$(Agent.TempDirectory)/dotnet-test-results"',
            f'Run .NET Tests: {test}'))
    if plan.get('dotnet_test_projects'):
        steps.append({
            'task': 'PublishTestResults@2', 'displayName': 'Publish .NET Test Results',
            'condition': 'succeededOrFailed()',
            'inputs': {'testResultsFormat': 'VSTest', 'testResultsFiles': '**/*.trx',
                       'searchFolder': '$(Agent.TempDirectory)/dotnet-test-results',
                       'failTaskOnFailedTests': True, 'failTaskOnMissingResultsFile': True},
        })
    # A test project's restore can overwrite a referenced app's assets file.
    # Restore/build the deployment RID after tests, so --no-restore publish reuses matching assets.
    steps.extend([
        command('restore', f'{project} --runtime {runtime} -p:TargetFramework={framework} {properties}', 'Restore .NET Application'),
        command('build', f'{build_arguments} --no-restore', 'Build .NET Application'),
        command('publish', f'{build_arguments} --no-build --no-restore '
                '--output "$(Build.ArtifactStagingDirectory)/publish"', 'Publish .NET Application'),
        {
            'pwsh': dedent(r'''
                $ErrorActionPreference = 'Stop'
                $required = @("$env:ASSEMBLY_NAME.dll", "$env:ASSEMBLY_NAME.deps.json", "$env:ASSEMBLY_NAME.runtimeconfig.json")
                if ($env:REQUIRE_EXE -eq 'true') { $required += "$env:ASSEMBLY_NAME.exe" }
                if ($env:REQUIRE_WEB_CONFIG -eq 'true') { $required += 'web.config' }
                foreach ($name in $required) {
                    $file = Join-Path $env:PUBLISH_PATH $name
                    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
                        throw "Publish output missing: $name"
                    }
                    if ((Get-Item -LiteralPath $file).Length -eq 0) {
                        throw "Publish output is empty: $name"
                    }
                }
            '''),
            'displayName': 'Validate .NET Publish Output',
            'env': {'ASSEMBLY_NAME': plan['dotnet_assembly_name'],
                    'PUBLISH_PATH': '$(Build.ArtifactStagingDirectory)/publish',
                    'REQUIRE_EXE': str(plan['dotnet_use_apphost']).lower(),
                    'REQUIRE_WEB_CONFIG': str(plan.get('deployment_target') == 'iis').lower()},
        },
        {
            'task': 'PublishPipelineArtifact@1', 'displayName': 'Publish Pipeline Artifact',
            'inputs': {'targetPath': '$(Build.ArtifactStagingDirectory)/publish',
                       'artifact': artifact_name, 'publishLocation': 'pipeline'},
        },
    ])
    return steps
