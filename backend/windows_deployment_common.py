from pathlib import PureWindowsPath
import re
from textwrap import dedent
from urllib.parse import urlparse


def validate_windows_destination(value: str):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Windows deployment klasörü gerekli.')
    path = PureWindowsPath(value)
    if (not path.is_absolute() or path == PureWindowsPath(path.anchor)
            or '..' in path.parts or any(part.endswith((' ', '.')) for part in path.parts[1:])
            or re.search(r'[<>"|?*\x00-\x1f]', value)
            or ':' in str(path.relative_to(path.anchor))):
        raise ValueError('Deployment yolu kök olmayan mutlak Windows klasörü olmalıdır.')


def validate_windows_name(value: str, label: str):
    if not isinstance(value, str) or not value.strip() or re.search(r'[/\\*?\[\]\x00-\x1f]', value):
        raise ValueError(f'Geçerli bir {label} gerekli.')


def validate_health_url(value: str | None, required=False):
    if not value and not required:
        return
    if not isinstance(value, str):
        raise ValueError('Health check URL gerekli.')
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('Health check için HTTP veya HTTPS URL gerekli.')


WINDOWS_DEPLOYMENT_FUNCTIONS = dedent(r'''
    $ErrorActionPreference = 'Stop'
    if ($env:OS -ne 'Windows_NT') { throw 'Windows deployment requires a Windows agent.' }

    function Assert-WindowsArchitecture {
        $architecture = $env:PROCESSOR_ARCHITECTURE
        if ($env:PROCESSOR_ARCHITEW6432) { $architecture = $env:PROCESSOR_ARCHITEW6432 }
        if ($env:DOTNET_RUNTIME -eq 'win-x64' -and $architecture -ne 'AMD64') { throw 'win-x64 requires an x64 Windows server.' }
        if ($env:DOTNET_RUNTIME -eq 'win-arm64' -and $architecture -ne 'ARM64') { throw 'win-arm64 requires an ARM64 Windows server.' }
        if ($env:DOTNET_RUNTIME -eq 'win-x86' -and $architecture -notin @('x86', 'AMD64')) { throw 'win-x86 requires an x86/x64 Windows server.' }
    }

    function Get-DeploymentPaths {
        Assert-WindowsArchitecture
        if ($env:BUILD_BUILDID -notmatch '^\d+$') { throw 'Azure DevOps Build ID is required.' }
        $source = [IO.Path]::GetFullPath($env:ARTIFACT_PATH).TrimEnd('\')
        $destination = [IO.Path]::GetFullPath($env:DEPLOYMENT_PATH).TrimEnd('\')
        if ($destination -eq [IO.Path]::GetPathRoot($destination).TrimEnd('\')) {
            throw 'Deployment to a drive/share root is forbidden.'
        }
        if ($source -eq $destination -or $source.StartsWith($destination + '\', [StringComparison]::OrdinalIgnoreCase) -or $destination.StartsWith($source + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Artifact and deployment paths must not overlap.'
        }
        foreach ($path in @($source, $destination)) {
            if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Directory not found: $path" }
            if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Deployment directory cannot be a reparse point: $path"
            }
        }
        $backup = "$destination.backup.$env:BUILD_BUILDID"
        $staging = "$destination.staging.$env:BUILD_BUILDID"
        if ((Test-Path -LiteralPath $backup) -or (Test-Path -LiteralPath $staging)) {
            throw 'Backup or staging directory already exists.'
        }
        return @{ Source = $source; Destination = $destination; Backup = $backup; Staging = $staging }
    }

    function Assert-PublishArtifact([string]$source) {
        if ((Get-ChildItem -LiteralPath $source -Force | Measure-Object).Count -eq 0) { throw 'Artifact directory is empty.' }
        if ($env:ASSEMBLY_NAME) {
            $required = @("$env:ASSEMBLY_NAME.dll", "$env:ASSEMBLY_NAME.deps.json", "$env:ASSEMBLY_NAME.runtimeconfig.json")
            if ($env:REQUIRE_EXE -eq 'true') { $required += "$env:ASSEMBLY_NAME.exe" }
            if ($env:REQUIRE_WEB_CONFIG -eq 'true') { $required += 'web.config' }
            foreach ($name in $required) {
                $file = Join-Path $source $name
                if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Artifact missing: $name" }
                if ((Get-Item -LiteralPath $file).Length -eq 0) { throw "Artifact file is empty: $name" }
            }
        }
    }

    function Invoke-DeploymentHealthCheck {
        if (-not $env:HEALTH_CHECK_URL) { return }
        for ($attempt = 1; $attempt -le 30; $attempt++) {
            try {
                $response = Invoke-WebRequest -Uri $env:HEALTH_CHECK_URL -UseBasicParsing -TimeoutSec 5
                if ($response.StatusCode -eq 200) { return }
            }
            catch { Write-Verbose "Health check attempt $attempt failed: $_" }
            if ($attempt -lt 30) { Start-Sleep -Seconds 2 }
        }
        throw 'Application HTTP health check failed.'
    }
''')
