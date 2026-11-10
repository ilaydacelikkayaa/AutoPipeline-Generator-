from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import yaml

from backend.iis_deployment_generator import generate_iis_deployment_steps
from backend.windows_service_deployment_generator import generate_windows_service_deployment_steps
from backend.windows_deployment_common import validate_windows_destination
from backend.pipeline_orchestrator import generate_for_discovered_repository


class WindowsDeploymentTest(unittest.TestCase):
    def iis(self, **kwargs):
        settings = dict(artifact_name='publish', app_pool_name='Web', site_path=r'C:\Sites\Web', health_check_url='http://localhost/health', assembly_name='MyWeb', dotnet_runtime='win-x64')
        settings.update(kwargs)
        return generate_iis_deployment_steps(**settings)

    def service(self, **kwargs):
        settings = dict(artifact_name='publish', service_name='Worker', install_path=r'C:\Services\Worker', assembly_name='MyWorker', dotnet_runtime='win-x64')
        settings.update(kwargs)
        return generate_windows_service_deployment_steps(**settings)

    def test_rejects_unsafe_windows_destinations(self):
        for path in ['', '.', 'C:\\', 'C:relative', r'C:\Sites\..\Windows', r'C:\Sites\*', r'\\server\share']:
            with self.assertRaises(ValueError, msg=path):
                validate_windows_destination(path)
        for path in [r'C:\Sites\My Web', r'\\server\share\Web']:
            validate_windows_destination(path)

    def test_names_and_non_http_health_checks_are_rejected(self):
        for name in ['', '*', 'Worker?', 'a/b', 'Pool[1]']:
            with self.assertRaises(ValueError):
                self.iis(app_pool_name=name)
            with self.assertRaises(ValueError):
                self.service(service_name=name)
        with self.assertRaises(ValueError):
            self.iis(health_check_url='file:///C:/health')
        with self.assertRaises(ValueError):
            self.service(health_check_url='file:///C:/health')
        with self.assertRaises(ValueError):
            self.iis(health_check_url=None)
        self.service(health_check_url=None)

    def test_iis_checks_actual_binding_hosting_module_and_bitness(self):
        step = self.iis()[0]
        self.assertIn('AspNetCoreModuleV2', step['powershell'])
        self.assertIn('Microsoft.Web.Administration.ServerManager', step['powershell'])
        self.assertIn("$application.VirtualDirectories['/'].PhysicalPath", step['powershell'])
        self.assertIn('$application.ApplicationPoolName', step['powershell'])
        self.assertIn('enable32BitAppOnWin64', step['powershell'])
        self.assertEqual(step['env']['ASSEMBLY_NAME'], 'MyWeb')
        self.assertEqual(step['env']['REQUIRE_WEB_CONFIG'], 'true')
        self.assertEqual(step['env']['REQUIRE_EXE'], 'false')

    def test_service_registration_must_match_publish_entrypoint(self):
        step = self.service()[0]
        self.assertIn('Win32_Service', step['powershell'])
        self.assertIn('BinaryPathName does not match', step['powershell'])
        self.assertIn("@('dotnet', 'dotnet.exe')", step['powershell'])
        self.assertEqual(step['env']['REQUIRE_EXE'], 'true')
        self.assertEqual(step['env']['ASSEMBLY_NAME'], 'MyWorker')
        self.assertEqual(step['env']['REQUIRE_WEB_CONFIG'], 'false')

    def test_artifact_and_path_checks_precede_stopping_application(self):
        for step in [self.iis()[1], self.service()[1]]:
            script = step['powershell']
            deployment = script[script.index('$paths = Get-DeploymentPaths'):]
            self.assertLess(deployment.index('Assert-PublishArtifact'), deployment.index('$stopRequested = $true'))
            self.assertLess(deployment.index('Copy-Item'), deployment.index('$stopRequested = $true'))
            self.assertLess(deployment.index('Set-Acl -LiteralPath $staging'), deployment.index('$stopRequested = $true'))
            self.assertIn('Get-Acl -LiteralPath $destination', deployment)
            self.assertIn('runtimeconfig.json', script)
            self.assertIn('Artifact missing', script)
            self.assertIn('must not overlap', script)
            self.assertIn('ReparsePoint', script)
            self.assertIn('BUILD_BUILDID', script)
            self.assertIn('Backup or staging directory already exists', script)

    def test_rollback_waits_before_removing_files_and_preserves_error(self):
        for step, wait in [(self.iis()[1], "Wait-AppPoolState $appPool 'Stopped'"), (self.service()[1], "Wait-ServiceState $serviceName 'Stopped'")]:
            script = step['powershell']
            rollback = script[script.index('$deploymentError = $_'):]
            self.assertLess(rollback.index(wait), rollback.index('Remove-Item -LiteralPath $destination'))
            self.assertIn('throw $deploymentError', rollback)
            self.assertIn('$initialState', rollback)
            self.assertIn('Rollback failed:', rollback)
            self.assertNotIn('Write-Error', rollback)
            self.assertIn('Staging cleanup failed:', rollback)

    def test_optional_worker_health_url_is_used(self):
        step = self.service(health_check_url='http://localhost:9000/health')[1]
        self.assertEqual(step['env']['HEALTH_CHECK_URL'], 'http://localhost:9000/health')
        self.assertIn('Invoke-DeploymentHealthCheck', step['powershell'])
        self.assertIn('Start-Sleep -Seconds 2', step['powershell'])
        self.assertIn('Windows Service stopped after startup', step['powershell'])

    def test_windows_pool_demands_and_agent_selection(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Web.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>')
            pipeline = yaml.safe_load(generate_for_discovered_repository(root, 'web', deployment_target='iis', app_pool_name='Web', site_path=r'C:\Sites\Web', health_check_url='http://localhost/health', agent_pool='Windows-Pool', agent_name='Server-01'))
            self.assertEqual(pipeline['jobs'][1]['pool'], {'name': 'Windows-Pool', 'demands': ['Agent.OS -equals Windows_NT', 'Agent.Name -equals Server-01']})
            self.assertEqual(pipeline['jobs'][1]['steps'][0]['task'], 'DownloadPipelineArtifact@2')
            self.assertEqual(pipeline['jobs'][1]['steps'][2]['env']['ASSEMBLY_NAME'], 'Web')

    def test_api_forwards_dotnet_and_agent_settings_to_pr(self):
        from backend.main import PullRequestRequest, create_pipeline_pr
        settings = dict(repository_url='https://dev.azure.com/org/project/_git/repo', repository_name='repo', project_name='project', deployment_target='iis', dotnet_project='src/Web.csproj', dotnet_framework='net9.0', dotnet_sdk_version='9.0.x', dotnet_runtime='win-x86', dotnet_self_contained=True, agent_name='server')
        with patch('backend.main.deploy_repository_pipeline', return_value={'status': 'DRY_RUN'}) as deploy:
            result = create_pipeline_pr(PullRequestRequest(**settings))
        self.assertEqual(result['status'], 'DRY_RUN')
        for key in ['dotnet_project', 'dotnet_framework', 'dotnet_sdk_version', 'dotnet_runtime', 'dotnet_self_contained', 'agent_name']:
            self.assertEqual(deploy.call_args.kwargs[key], settings[key])
