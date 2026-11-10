from textwrap import dedent

from backend.windows_deployment_common import (
    WINDOWS_DEPLOYMENT_FUNCTIONS, validate_health_url,
    validate_windows_destination, validate_windows_name,
)


IIS_FUNCTIONS = dedent(r'''
    Import-Module WebAdministration -ErrorAction Stop

    function Wait-AppPoolState([string]$name, [string]$expected) {
        $deadline = (Get-Date).AddSeconds(60)
        do {
            if ((Get-WebAppPoolState -Name $name).Value -eq $expected) { return }
            Start-Sleep -Seconds 2
        } while ((Get-Date) -lt $deadline)
        throw "Application Pool did not reach state: $expected"
    }

    function Assert-IisTarget([string]$destination) {
        $name = $env:APP_POOL_NAME
        if (-not (Test-Path -LiteralPath "IIS:\AppPools\$name")) { throw "Application Pool not found: $name" }
        if (-not (Get-WebGlobalModule -Name AspNetCoreModuleV2)) { throw 'ASP.NET Core Hosting Bundle / AspNetCoreModuleV2 is required.' }
        [void][Reflection.Assembly]::LoadFrom((Join-Path $env:windir 'System32\inetsrv\Microsoft.Web.Administration.dll'))
        $manager = New-Object Microsoft.Web.Administration.ServerManager
        $matching = 0
        try {
            foreach ($site in $manager.Sites) {
                foreach ($application in $site.Applications) {
                    $physicalPath = $application.VirtualDirectories['/'].PhysicalPath
                    if ($physicalPath -and $application.ApplicationPoolName -eq $name -and
                        [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($physicalPath)).TrimEnd('\') -eq $destination) {
                        if ($site.State.ToString() -ne 'Started') { throw 'IIS site must be started before deployment.' }
                        $matching++
                    }
                }
            }
        }
        finally { $manager.Dispose() }
        if ($matching -eq 0) { throw 'IIS physicalPath/applicationPool does not match the deployment target.' }
        $pool = Get-Item -LiteralPath "IIS:\AppPools\$name"
        if ([Environment]::Is64BitOperatingSystem -and $env:DOTNET_RUNTIME -eq 'win-x86' -and -not $pool.enable32BitAppOnWin64) { throw 'win-x86 requires a 32-bit IIS application pool.' }
        if ($env:DOTNET_RUNTIME -eq 'win-x64' -and $pool.enable32BitAppOnWin64) { throw 'win-x64 requires a 64-bit IIS application pool.' }
    }
''')


def generate_iis_deployment_steps(
    artifact_name: str,
    app_pool_name: str,
    site_path: str,
    health_check_url: str,
    assembly_name: str | None = None,
    dotnet_runtime: str | None = None,
    require_exe: bool = False,
) -> list:
    validate_windows_name(app_pool_name, 'IIS Application Pool adı')
    validate_windows_destination(site_path)
    validate_health_url(health_check_url, required=True)
    functions = WINDOWS_DEPLOYMENT_FUNCTIONS + IIS_FUNCTIONS
    check_script = functions + dedent(r'''
        $paths = Get-DeploymentPaths
        Assert-PublishArtifact $paths.Source
        Assert-IisTarget $paths.Destination
    ''')
    deploy_script = functions + dedent(r'''
        $paths = Get-DeploymentPaths
        Assert-PublishArtifact $paths.Source
        Assert-IisTarget $paths.Destination
        $source = $paths.Source
        $destination = $paths.Destination
        $backup = $paths.Backup
        $staging = $paths.Staging
        $appPool = $env:APP_POOL_NAME
        $initialState = (Get-WebAppPoolState -Name $appPool).Value
        if ($initialState -notin @('Started', 'Stopped')) { throw 'IIS application pool is transitioning; retry later.' }
        $stopRequested = $false
        $oldMoved = $false
        $newMoved = $false
        try {
            $directoryAcl = Get-Acl -LiteralPath $destination
            New-Item -ItemType Directory -Path $staging | Out-Null
            Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $staging -Recurse -Force
            Set-Acl -LiteralPath $staging -AclObject $directoryAcl
            $stopRequested = $true
            if ((Get-WebAppPoolState -Name $appPool).Value -ne 'Stopped') { Stop-WebAppPool -Name $appPool }
            Wait-AppPoolState $appPool 'Stopped'
            Move-Item -LiteralPath $destination -Destination $backup
            $oldMoved = $true
            Move-Item -LiteralPath $staging -Destination $destination
            $newMoved = $true
            Start-WebAppPool -Name $appPool
            Wait-AppPoolState $appPool 'Started'
            Invoke-DeploymentHealthCheck
            Write-Host 'IIS deployment completed successfully.'
        }
        catch {
            $deploymentError = $_
            Write-Warning 'Deployment failed. Attempting rollback.'
            try {
                if ($oldMoved) {
                    if ((Get-WebAppPoolState -Name $appPool).Value -ne 'Stopped') { Stop-WebAppPool -Name $appPool }
                    Wait-AppPoolState $appPool 'Stopped'
                    if ($newMoved -and (Test-Path -LiteralPath $destination)) { Remove-Item -LiteralPath $destination -Recurse -Force }
                    Move-Item -LiteralPath $backup -Destination $destination
                }
                if ($stopRequested) {
                    if ($initialState -eq 'Started') {
                        if ((Get-WebAppPoolState -Name $appPool).Value -ne 'Started') { Start-WebAppPool -Name $appPool }
                        Wait-AppPoolState $appPool 'Started'
                    }
                    else {
                        if ((Get-WebAppPoolState -Name $appPool).Value -ne 'Stopped') { Stop-WebAppPool -Name $appPool }
                        Wait-AppPoolState $appPool 'Stopped'
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
        'DEPLOYMENT_PATH': site_path, 'SITE_PATH': site_path,
        'APP_POOL_NAME': app_pool_name, 'HEALTH_CHECK_URL': health_check_url,
        'ASSEMBLY_NAME': assembly_name or '', 'DOTNET_RUNTIME': dotnet_runtime or '',
        'REQUIRE_EXE': str(require_exe).lower(), 'REQUIRE_WEB_CONFIG': 'true',
    }
    return [
        {'powershell': check_script, 'displayName': 'Check IIS Application Pool', 'env': env.copy()},
        {'powershell': deploy_script, 'displayName': 'Deploy IIS Application', 'env': env.copy()},
    ]
