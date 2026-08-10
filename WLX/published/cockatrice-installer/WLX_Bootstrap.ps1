[CmdletBinding()]
param(
    [switch]$InstallShortcut,
    [switch]$RepairPictures,
    [switch]$NoLaunch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-Step([string]$Message) {
    Write-Host "[WLX] $Message" -ForegroundColor Cyan
}

if (-not $env:LOCALAPPDATA) { throw "Windows LOCALAPPDATA is unavailable." }
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$installRoot = Join-Path $env:LOCALAPPDATA "WillexsWhimsicalArts"
New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
$legacyInstallRoot = ""
if ("AlexCockatriceAltArt") {
    $candidateLegacyRoot = Join-Path $env:LOCALAPPDATA "AlexCockatriceAltArt"
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals($candidateLegacyRoot, $installRoot) -and
        (Test-Path -LiteralPath $candidateLegacyRoot -PathType Container)) {
        $legacyInstallRoot = $candidateLegacyRoot
        $newSettingsPath = Join-Path $installRoot "installer_settings.json"
        if (-not (Test-Path -LiteralPath $newSettingsPath -PathType Leaf)) {
            foreach ($legacySettingsName in @("installer_settings.json", "friend_settings.json")) {
                $candidateSettings = Join-Path $legacyInstallRoot $legacySettingsName
                if (Test-Path -LiteralPath $candidateSettings -PathType Leaf) {
                    Copy-Item -LiteralPath $candidateSettings -Destination $newSettingsPath
                    Write-Step "Migrated the previous updater settings."
                    break
                }
            }
        }
    }
}
$localConfigPath = Join-Path $installRoot "installer_config.json"
if (-not (Test-Path -LiteralPath $localConfigPath -PathType Leaf)) {
    $localConfigPath = Join-Path $scriptRoot "installer_config.json"
}
$config = Read-JsonFile $localConfigPath
if ([string]$config.package_id -ne "willexs-whimsical-arts") {
    throw "The installer configuration belongs to a different package."
}
$manifestUrl = [string]$config.manifest_url
if (-not [Uri]::IsWellFormedUriString($manifestUrl, [UriKind]::Absolute)) {
    throw "The installer configuration has an invalid manifest URL."
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Step "Checking the current installer and publication..."
$manifest = (Invoke-WebRequest -UseBasicParsing -Uri $manifestUrl -TimeoutSec 30).Content | ConvertFrom-Json
if ([int]$manifest.schema_version -ne 1 -or [string]$manifest.package_id -ne "willexs-whimsical-arts") {
    throw "The hosted manifest is incompatible with this WLX installation."
}
if ($manifest.PSObject.Properties.Name -contains "release_ready" -and -not [bool]$manifest.release_ready) {
    throw "The hosted release is marked unfinished."
}

$installerInfo = $null
if ($manifest.PSObject.Properties.Name -contains "cockatrice_installer") {
    $installerInfo = $manifest.cockatrice_installer
}
if ($null -eq $installerInfo) { throw "The hosted manifest has no Cockatrice installer entry." }
$expectedHash = ([string]$installerInfo.sha256).ToLowerInvariant()
if ($expectedHash -notmatch "^[0-9a-f]{64}$") { throw "The installer SHA-256 is invalid." }
$installerUrl = [string]$installerInfo.url
if (-not [Uri]::IsWellFormedUriString($installerUrl, [UriKind]::Absolute)) {
    $installerUrl = ([Uri]::new([Uri]$manifestUrl, [string]$installerInfo.path)).AbsoluteUri
}

$bridgeStatePath = Join-Path $installRoot "bridge_state.json"
$installedHash = ""
if (Test-Path -LiteralPath $bridgeStatePath -PathType Leaf) {
    try {
        $bridgeState = Read-JsonFile $bridgeStatePath
        $installedHash = ([string]$bridgeState.installer_sha256).ToLowerInvariant()
    } catch {
        $installedHash = ""
    }
}

if ($installedHash -ne $expectedHash) {
    $stagingRoot = Join-Path $env:TEMP ("wlx-installer-" + [Guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $stagingRoot "installer.zip"
    $extractPath = Join-Path $stagingRoot "extracted"
    New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
    try {
        Write-Step "Downloading and verifying the current WLX Cockatrice Installer..."
        Invoke-WebRequest -UseBasicParsing -Uri $installerUrl -OutFile $zipPath -TimeoutSec 60
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "The downloaded installer failed SHA-256 verification."
        }
        Expand-Archive -LiteralPath $zipPath -DestinationPath $extractPath -Force
        $required = @(
            "WLX_Cockatrice_Updater.ps1",
            "REPAIR_ART.bat",
            "UNINSTALL.bat",
            "README_FOR_PLAYERS.txt",
            "installer_config.json"
        )
        foreach ($filename in $required) {
            $candidate = Join-Path $extractPath $filename
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                throw "The verified installer archive is incomplete: $filename"
            }
        }
        $downloadedConfig = Read-JsonFile (Join-Path $extractPath "installer_config.json")
        if ([string]$downloadedConfig.package_id -ne "willexs-whimsical-arts") {
            throw "The verified installer archive belongs to a different package."
        }
        foreach ($filename in $required) {
            Copy-Item -LiteralPath (Join-Path $extractPath $filename) -Destination (Join-Path $installRoot $filename) -Force
        }
        [ordered]@{
            schema_version = 1
            package_id = "willexs-whimsical-arts"
            version = [string]$manifest.version
            installer_sha256 = $expectedHash
            refreshed_at = (Get-Date).ToUniversalTime().ToString("o")
        } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $bridgeStatePath -Encoding UTF8
        Write-Step "The installed updater is current."
    } finally {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$updater = Join-Path $installRoot "WLX_Cockatrice_Updater.ps1"
if (-not (Test-Path -LiteralPath $updater -PathType Leaf)) {
    $updater = Join-Path $scriptRoot "WLX_Cockatrice_Updater.ps1"
}
$arguments = @(
    "-NoLogo",
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $updater,
    "-ManifestUrl",
    $manifestUrl
)
if ($InstallShortcut) { $arguments += "-InstallShortcut" }
if ($RepairPictures) { $arguments += "-RepairPictures" }
if ($NoLaunch) { $arguments += "-NoLaunch" }
& powershell.exe @arguments
$updaterResult = $LASTEXITCODE
if ($updaterResult -eq 0 -and $legacyInstallRoot -and
    (Test-Path -LiteralPath $legacyInstallRoot -PathType Container)) {
    $migrationBackup = Join-Path $installRoot "migration-backup"
    New-Item -ItemType Directory -Path $migrationBackup -Force | Out-Null
    $legacyName = Split-Path -Leaf $legacyInstallRoot
    $destination = Join-Path $migrationBackup ($legacyName + "-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    if (Test-Path -LiteralPath $destination) {
        $destination += "-" + [Guid]::NewGuid().ToString("N")
    }
    Move-Item -LiteralPath $legacyInstallRoot -Destination $destination
    Write-Step "Archived the previous updater folder at $destination"
}
exit $updaterResult
