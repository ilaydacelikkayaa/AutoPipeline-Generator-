from textwrap import dedent

from backend.windows_deployment_common import (
    WINDOWS_DEPLOYMENT_FUNCTIONS, validate_health_url,
    validate_windows_destination, validate_windows_name,
)


SERVICE_FUNCTIONS = dedent(r'''
    function Wait-ServiceState([string]$name, [string]$expected) {
        $service = Get-Service -Name $name -ErrorAction Stop
        $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]$expected, [TimeSpan]::FromSeconds(60))
    }

    function Assert-ServiceTarget([string]$destination) {
        $serviceName = $env:SERVICE_NAME
        $service = Get-Service -Name $serviceName -ErrorAction Stop
        if ($env:ASSEMBLY_NAME) {
            $registration = Get-CimInstance -ClassName Win32_Service | Where-Object { $_.Name -eq $serviceName }
            if (-not $registration) { throw 'Windows service registration not found.' }
            $command = [Environment]::ExpandEnvironmentVariables($registration.PathName)
            $tokens = @([regex]::Matches($command, '"([^"]*)"|(\S+)') | ForEach-Object {
                if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value }
            })
            if ($tokens.Count -eq 0) { throw 'Windows service BinaryPathName is empty.' }
            $entrypoint = $tokens[0]
            $expected = Join-Path $destination "$env:ASSEMBLY_NAME.exe"
            if ([IO.Path]::GetFileName($entrypoint) -in @('dotnet', 'dotnet.exe')) {
                if ($tokens.Count -lt 2) { throw 'Service dotnet DLL entrypoint is missing.' }
                $entrypoint = $tokens[1]
                $expected = Join-Path $destination "$env:ASSEMBLY_NAME.dll"
            }
            if (-not [IO.Path]::IsPathRooted($entrypoint) -or [IO.Path]::GetFullPath($entrypoint) -ne $expected) {
                throw 'Service BinaryPathName does not match the publish assembly and installation path.'
            }
        }
    }
''')


def generate_windows_service_deployment_steps(
    artifact_name: str,
    service_name: str,
    install_path: str,
    assembly_name: str | None = None,
    health_check_url: str | None = None,
    dotnet_runtime: str | None = None,
) -> list:
    validate_windows_name(service_name, 'Windows Service adı')
    validate_windows_destination(install_path)
    validate_health_url(health_check_url)
    functions = WINDOWS_DEPLOYMENT_FUNCTIONS + SERVICE_FUNCTIONS
    check_script = functions + dedent(r'''
        $paths = Get-DeploymentPaths
        Assert-PublishArtifact $paths.Source
        Assert-ServiceTarget $paths.Destination
    ''')
    deploy_script = functions + dedent(r'''
        $paths = Get-DeploymentPaths
        Assert-PublishArtifact $paths.Source
        Assert-ServiceTarget $paths.Destination
        $source = $paths.Source
        $destination = $paths.Destination
        $backup = $paths.Backup
        $staging = $paths.Staging
        $serviceName = $env:SERVICE_NAME
        $initialState = (Get-Service -Name $serviceName).Status.ToString()
        if ($initialState -notin @('Running', 'Stopped')) { throw 'Service is transitioning/paused; retry after checking its state.' }
        $stopRequested = $false
        $oldMoved = $false
        $newMoved = $false
        try {
            $directoryAcl = Get-Acl -LiteralPath $destination
            New-Item -ItemType Directory -Path $staging | Out-Null
            Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $staging -Recurse -Force
            Set-Acl -LiteralPath $staging -AclObject $directoryAcl
            $stopRequested = $true
            if ((Get-Service -Name $serviceName).Status -ne 'Stopped') { Stop-Service -Name $serviceName -ErrorAction Stop }
            Wait-ServiceState $serviceName 'Stopped'
            Move-Item -LiteralPath $destination -Destination $backup
            $oldMoved = $true
            Move-Item -LiteralPath $staging -Destination $destination
            $newMoved = $true
            Start-Service -Name $serviceName -ErrorAction Stop
            Wait-ServiceState $serviceName 'Running'
            Start-Sleep -Seconds 5
            if ((Get-Service -Name $serviceName).Status -ne 'Running') { throw 'Windows Service stopped after startup.' }
            Invoke-DeploymentHealthCheck
            Write-Host 'Windows Service deployment completed successfully.'
        }
        catch {
            $deploymentError = $_
            Write-Warning 'Deployment failed. Attempting rollback.'
            try {
                if ($oldMoved) {
                    if ((Get-Service -Name $serviceName).Status -ne 'Stopped') { Stop-Service -Name $serviceName -ErrorAction Stop }
                    Wait-ServiceState $serviceName 'Stopped'
                    if ($newMoved -and (Test-Path -LiteralPath $destination)) { Remove-Item -LiteralPath $destination -Recurse -Force }
                    Move-Item -LiteralPath $backup -Destination $destination
                }
                if ($stopRequested) {
                    if ($initialState -eq 'Running') {
                        if ((Get-Service -Name $serviceName).Status -ne 'Running') { Start-Service -Name $serviceName -ErrorAction Stop }
                        Wait-ServiceState $serviceName 'Running'
                    }
                    else {
                        if ((Get-Service -Name $serviceName).Status -ne 'Stopped') { Stop-Service -Name $serviceName -ErrorAction Stop }
                        Wait-ServiceState $serviceName 'Stopped'
                    }
                }
                Write-Host 'Rollback completed.'
            }
            catch { Write-Warning "Rollback failed: $_" }
            throw $deploymentError
        }
        finally {
            try {
                if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
            }
            catch { Write-Warning "Staging cleanup failed: $_" }
        }
    ''')
    env = {
        'ARTIFACT_PATH': r'$(Pipeline.Workspace)\downloaded',
        'DEPLOYMENT_PATH': install_path, 'INSTALL_PATH': install_path,
        'SERVICE_NAME': service_name, 'ASSEMBLY_NAME': assembly_name or '',
        'HEALTH_CHECK_URL': health_check_url or '',
        'DOTNET_RUNTIME': dotnet_runtime or '',
        'REQUIRE_EXE': 'true', 'REQUIRE_WEB_CONFIG': 'false',
    }
    return [
        {'powershell': check_script, 'displayName': 'Check Windows Service', 'env': env.copy()},
        {'powershell': deploy_script, 'displayName': 'Deploy Windows Service', 'env': env.copy()},
    ]
