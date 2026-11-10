import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from backend.dotnet_project_resolver import resolve_dotnet_project
from backend.pipeline_orchestrator import generate_for_discovered_repository, generate_for_repository


def project(root, name='src/Web/Web.csproj', sdk='Microsoft.NET.Sdk.Web', framework='net8.0', extra=''):
    file = root / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(f'<Project Sdk="{sdk}"><PropertyGroup><TargetFramework>{framework}</TargetFramework>{extra}</PropertyGroup></Project>')
    return file


class DotnetPipelineTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def resolve(self, target='iis', **config):
        return resolve_dotnet_project(self.root, self.root, target, config)

    def generate(self, target='iis', **kwargs):
        options = dict(app_pool_name='WebPool', site_path=r'C:\Sites\Web', health_check_url='http://localhost/health') if target == 'iis' else dict(service_name='Worker', install_path=r'C:\Services\Worker')
        return yaml.safe_load(generate_for_discovered_repository(self.root, 'app', deployment_target=target, **options, **kwargs))

    def test_web_selected_over_library_and_test(self):
        project(self.root)
        project(self.root, 'src/Library/Library.csproj', sdk='Microsoft.NET.Sdk')
        project(self.root, 'tests/Web.Tests.csproj', sdk='Microsoft.NET.Sdk', extra='<IsTestProject>true</IsTestProject>')
        result = self.resolve()
        self.assertEqual(result['dotnet_project'], 'src/Web/Web.csproj')
        self.assertEqual(result['dotnet_sdk_version'], '8.0.x')
        self.assertEqual(result['dotnet_test_projects'], ['tests/Web.Tests.csproj'])
        self.assertFalse(result['dotnet_use_apphost'])
        self.assertFalse(result['dotnet_self_contained'])

    def test_multiple_web_projects_need_explicit_selection(self):
        project(self.root)
        project(self.root, 'src/Other/Other.csproj')
        with self.assertRaisesRegex(ValueError, 'dotnet_project'):
            self.resolve()
        self.assertEqual(self.resolve(dotnet_project='src/Other/Other.csproj')['dotnet_project'], 'src/Other/Other.csproj')

    def test_test_and_non_web_projects_cannot_be_published_to_iis(self):
        project(self.root, sdk='Microsoft.NET.Sdk', extra='<IsTestProject>true</IsTestProject>')
        with self.assertRaisesRegex(ValueError, 'Test projesi'):
            self.resolve(dotnet_project='src/Web/Web.csproj')
        project(self.root, sdk='Microsoft.NET.Sdk', extra='<OutputType>Exe</OutputType>')
        with self.assertRaisesRegex(ValueError, 'Web projesi'):
            self.resolve(dotnet_project='src/Web/Web.csproj')

    def test_worker_needs_windows_service_hosting_evidence(self):
        file = project(self.root, 'src/Worker/Worker.csproj', sdk='Microsoft.NET.Sdk.Worker', extra='<OutputType>Exe</OutputType>')
        with self.assertRaisesRegex(ValueError, 'Windows Service'):
            self.resolve('windows-service', dotnet_project='src/Worker/Worker.csproj')
        (file.parent / 'Program.cs').write_text('// builder.Services.AddWindowsService();')
        with self.assertRaises(ValueError):
            self.resolve('windows-service')
        (file.parent / 'Program.cs').write_text('builder.Services.AddWindowsService();')
        result = self.resolve('windows-service')
        self.assertTrue(result['dotnet_use_apphost'])
        self.assertEqual(result['dotnet_runtime'], 'win-x64')

    def test_worker_does_not_borrow_evidence_from_nested_other_project(self):
        file = project(self.root, 'Worker.csproj', sdk='Microsoft.NET.Sdk.Worker')
        other = project(self.root, 'Other/Other.csproj', sdk='Microsoft.NET.Sdk.Worker')
        (other.parent / 'Program.cs').write_text('builder.Services.AddWindowsService();')
        with self.assertRaisesRegex(ValueError, 'Windows Service'):
            self.resolve('windows-service', dotnet_project=file.name)

    def test_frameworks_require_selection(self):
        file = project(self.root)
        file.write_text('<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFrameworks>net8.0;net9.0</TargetFrameworks></PropertyGroup></Project>')
        with self.assertRaisesRegex(ValueError, 'dotnet_framework'):
            self.resolve()
        self.assertEqual(self.resolve(dotnet_framework='net9.0')['dotnet_sdk_version'], '9.0.x')
        with self.assertRaises(ValueError):
            self.resolve(dotnet_framework='net10.0')

    def test_global_json_and_working_directory(self):
        project(self.root)
        (self.root / 'global.json').write_text(json.dumps({'sdk': {'version': '9.0.203', 'rollForward': 'latestPatch'}}))
        result = self.resolve()
        self.assertEqual(result['dotnet_sdk_version'], '9.0.203')
        self.assertEqual(result['dotnet_global_json'], 'global.json')
        pipeline = self.generate()
        sdk = next(step for step in pipeline['jobs'][0]['steps'] if step.get('task') == 'UseDotNet@2')
        self.assertTrue(sdk['inputs']['useGlobalJson'])
        self.assertNotIn('version', sdk['inputs'])
        self.assertEqual(sdk['inputs']['workingDirectory'], '$(Build.SourcesDirectory)')
        commands = [step for step in pipeline['jobs'][0]['steps'] if step.get('task') == 'DotNetCoreCLI@2']
        self.assertTrue(all(s['inputs']['workingDirectory'].endswith('/src/Web') for s in commands))
        with self.assertRaisesRegex(ValueError, 'çelişiyor'):
            self.resolve(dotnet_sdk_version='8.0.x')

    def test_bad_and_old_global_sdk_are_rejected(self):
        project(self.root)
        for version in ['8.0.x', '7.0.100']:
            (self.root / 'global.json').write_text(json.dumps({'sdk': {'version': version}}))
            with self.assertRaises(ValueError):
                self.resolve()

    def test_directory_props_are_used(self):
        file = project(self.root)
        file.write_text('<Project Sdk="Microsoft.NET.Sdk.Web" />')
        (self.root / 'Directory.Build.props').write_text('<Project><PropertyGroup><VersionFramework>net9.0</VersionFramework><TargetFramework>$(VersionFramework)</TargetFramework></PropertyGroup></Project>')
        self.assertEqual(self.resolve()['dotnet_framework'], 'net9.0')

    def test_incomplete_legacy_and_malformed_projects_fail(self):
        file = project(self.root)
        for content in ['<Project Sdk="Microsoft.NET.Sdk.Web" />', '<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net48</TargetFramework></PropertyGroup></Project>', '<Project>']:
            file.write_text(content)
            with self.assertRaises(ValueError):
                self.resolve()

    def test_invalid_paths_runtime_sdk_and_assembly_are_rejected(self):
        project(self.root)
        for options in [dict(dotnet_project='../outside.csproj'), dict(dotnet_runtime='linux-x64'), dict(dotnet_runtime='win-arm64'), dict(dotnet_sdk_version='8.0.x; echo bad'), dict(dotnet_self_contained='false')]:
            with self.assertRaises(ValueError):
                self.resolve(**options)
        project(self.root, extra='<AssemblyName>../outside</AssemblyName>')
        with self.assertRaises(ValueError):
            self.resolve()

    def test_generated_commands_select_project_and_share_publish_options(self):
        project(self.root, 'src/My Web/Web.csproj')
        pipeline = self.generate(dotnet_runtime='win-x86', dotnet_self_contained=True)
        build = pipeline['jobs'][0]
        self.assertEqual(build['pool'], {'vmImage': 'windows-latest'})
        commands = {s['inputs']['custom']: s['inputs'] for s in build['steps'] if s.get('task') == 'DotNetCoreCLI@2'}
        for command in ['restore', 'build', 'publish']:
            args = commands[command]['arguments']
            self.assertIn('"$(Build.SourcesDirectory)/src/My Web/Web.csproj"', args)
            self.assertIn('--runtime win-x86', args)
            self.assertIn('-p:SelfContained=true', args)
            self.assertIn('-p:UseAppHost=true', args)
            self.assertIn('-p:PublishSingleFile=false', args)
        self.assertIn('--no-build --no-restore', commands['publish']['arguments'])
        self.assertIn('$(Build.ArtifactStagingDirectory)/publish', commands['publish']['arguments'])
        self.assertNotIn('test', commands)

    def test_test_projects_are_built_separately_and_results_published(self):
        project(self.root)
        test = project(self.root, 'tests/Tests.csproj', sdk='Microsoft.NET.Sdk', extra='<IsTestProject>true</IsTestProject>')
        steps = self.generate()['jobs'][0]['steps']
        tests = [s for s in steps if s.get('inputs', {}).get('custom') == 'test']
        self.assertEqual(len(tests), 1)
        args = tests[0]['inputs']['arguments']
        self.assertIn('tests/Tests.csproj', args)
        self.assertNotIn('--no-build', args)
        self.assertNotIn('--runtime', args)
        self.assertTrue(any(s.get('task') == 'PublishTestResults@2' for s in steps))
        commands = [s['inputs']['custom'] for s in steps if s.get('task') == 'DotNetCoreCLI@2']
        # A native test restore must not replace the final Windows RID assets used by publish.
        self.assertEqual(commands, ['test', 'restore', 'build', 'publish'])

    def test_config_project_path_and_settings(self):
        project(self.root, 'apps/Web/Web.csproj')
        config = self.root / 'config.yaml'
        config.write_text(yaml.safe_dump({
            'project': {'name': 'web', 'path': 'apps', 'branch': 'release'},
            'pipeline': {'dotnet_project': 'Web/Web.csproj', 'dotnet_runtime': 'win-x86', 'dotnet_self_contained': False},
            'deployment': {'target': 'iis', 'app_pool_name': 'WebPool', 'site_path': r'C:\Sites\Web', 'health_check_url': 'http://localhost/health'},
        }))
        pipeline = yaml.safe_load(generate_for_repository(self.root, str(config)))
        self.assertEqual(pipeline['trigger'], ['release'])
        self.assertIn('--runtime win-x86', str(pipeline))
        self.assertIn('apps/Web/Web.csproj', str(pipeline))

    def test_repeated_dotnet_yaml_is_identical_and_skip(self):
        from backend.pipeline_deployer import compare_pipeline_yaml, decide_pipeline_deployment
        project(self.root)
        first = generate_for_discovered_repository(self.root, 'app', deployment_target='iis', app_pool_name='Web', site_path=r'C:\Sites\Web', health_check_url='http://localhost/health')
        (self.root / 'azure-pipelines.generated.yml').write_text(first)
        self.assertEqual(decide_pipeline_deployment(compare_pipeline_yaml(self.root, first)), 'SKIP')


class DotnetSdkEvidenceTest(unittest.TestCase):
    def test_newer_test_framework_requires_newer_sdk(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project(root)
            project(root, 'tests/Tests.csproj', sdk='Microsoft.NET.Sdk', framework='net9.0', extra='<IsTestProject>true</IsTestProject>')
            result = resolve_dotnet_project(root, root, 'iis', {})
            self.assertEqual(result['dotnet_sdk_version'], '9.0.x')
            (root / 'global.json').write_text(json.dumps({'sdk': {'version': '8.0.100'}}))
            with self.assertRaisesRegex(ValueError, 'yetersiz'):
                resolve_dotnet_project(root, root, 'iis', {})

    def test_generated_obj_projects_do_not_create_ambiguity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project(root)
            project(root, 'src/Web/obj/Generated.csproj')
            self.assertEqual(resolve_dotnet_project(root, root, 'iis', {})['dotnet_project'], 'src/Web/Web.csproj')

    def test_aot_requires_an_explicitly_supported_deployment_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project(root, extra='<PublishAot>true</PublishAot>')
            with self.assertRaisesRegex(ValueError, 'AOT'):
                resolve_dotnet_project(root, root, 'iis', {})


class DotnetInheritedPropertiesTest(unittest.TestCase):
    def test_nearest_props_and_project_assembly_name(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            file = project(root)
            file.write_text('<Project Sdk="Microsoft.NET.Sdk.Web" />')
            (root / 'Directory.Build.props').write_text('<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
            (file.parent / 'Directory.Build.props').write_text('<Project><PropertyGroup><TargetFramework>net8.0</TargetFramework><AssemblyName>$(MSBuildProjectName).Host</AssemblyName></PropertyGroup></Project>')
            result = resolve_dotnet_project(root, root, 'iis', {})
            self.assertEqual(result['dotnet_framework'], 'net8.0')
            self.assertEqual(result['dotnet_assembly_name'], 'Web.Host')
