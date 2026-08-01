[CmdletBinding()]
param(
    [string]$ManifestUrl = "",
    [string]$CockatriceDataDir = "",
    [string]$CockatriceExe = "",
    [switch]$NoLaunch,
    [switch]$InstallShortcut,
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step([string]$Message) {
    Write-Host "[Alt Art] $Message" -ForegroundColor Cyan
}

function Test-Placeholder([string]$Value) {
    return $Value -match "YOUR_|REPLACE_ME|EXAMPLE\.COM|USERNAME/REPOSITORY"
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Find-CockatriceExe([string]$Explicit, $Settings) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Explicit) { $candidates.Add($Explicit) }
    if ($Settings -and $Settings.PSObject.Properties.Name -contains "cockatrice_exe" -and $Settings.cockatrice_exe) {
        $candidates.Add([string]$Settings.cockatrice_exe)
    }
    if ($env:ProgramFiles) {
        $candidates.Add((Join-Path $env:ProgramFiles "Cockatrice\Cockatrice.exe"))
    }
    if (${env:ProgramFiles(x86)}) {
        $candidates.Add((Join-Path ${env:ProgramFiles(x86)} "Cockatrice\Cockatrice.exe"))
    }
    if ($env:LOCALAPPDATA) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Cockatrice\Cockatrice.exe"))
        $candidates.Add((Join-Path $env:LOCALAPPDATA "Cockatrice\Cockatrice.exe"))
    }
    try {
        $fromPath = Get-Command "Cockatrice.exe" -ErrorAction Stop
        $candidates.Add($fromPath.Source)
    } catch {
        # Cockatrice is simply not on PATH.
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

function New-LaunchShortcut([string]$InstallRoot, [string]$ExePath) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    if (-not $desktop) { return }
    $shortcutPath = Join-Path $desktop "Alex's Cockatrice Alternate Art.lnk"
    $batchPath = Join-Path $InstallRoot "UPDATE_AND_LAUNCH.bat"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $env:ComSpec
    $shortcut.Arguments = "/c `"`"$batchPath`"`""
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.Description = "Update Alex's Cockatrice Alternate Art and launch Cockatrice"
    if ($ExePath) { $shortcut.IconLocation = "$ExePath,0" }
    $shortcut.Save()
    Write-Step "Desktop shortcut created: $shortcutPath"
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$config = Read-JsonFile (Join-Path $scriptRoot "friend_config.json")
if ([string]$config.package_id -ne "alex-cockatrice-alt-art") {
    throw "The installer configuration belongs to a different package."
}

if (-not $env:LOCALAPPDATA) {
    throw "Windows LOCALAPPDATA is unavailable."
}
$installRoot = Join-Path $env:LOCALAPPDATA ([string]$config.install_folder)
New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
$settingsPath = Join-Path $installRoot "friend_settings.json"
$statePath = Join-Path $installRoot "installed_state.json"
$settings = $null
if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
    $settings = Read-JsonFile $settingsPath
}

if ($Uninstall) {
    Write-Step "Removing the installed Cockatrice XML without touching other custom sets."
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        $state = Read-JsonFile $statePath
        if ($state.PSObject.Properties.Name -contains "installed_xml" -and $state.installed_xml) {
            $installedXml = [string]$state.installed_xml
            if (Test-Path -LiteralPath $installedXml -PathType Leaf) {
                $removedDir = Join-Path $installRoot "removed"
                New-Item -ItemType Directory -Path $removedDir -Force | Out-Null
                $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
                $removedName = "$(Split-Path -Leaf $installedXml).removed-$stamp"
                Move-Item -LiteralPath $installedXml -Destination (Join-Path $removedDir $removedName) -Force
                Write-Step "The XML was moved to $removedDir and can be recovered."
            }
        }
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    }
    $shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Alex's Cockatrice Alternate Art.lnk"
    Remove-Item -LiteralPath $shortcut -Force -ErrorAction SilentlyContinue
    Write-Step "Uninstall complete. The updater folder was left in place for recovery/logs."
    exit 0
}

if (-not $ManifestUrl) {
    if ($settings -and $settings.PSObject.Properties.Name -contains "manifest_url" -and $settings.manifest_url) {
        $ManifestUrl = [string]$settings.manifest_url
    } else {
        $ManifestUrl = [string]$config.manifest_url
    }
}
if (-not [Uri]::IsWellFormedUriString($ManifestUrl, [UriKind]::Absolute) -or (Test-Placeholder $ManifestUrl)) {
    throw "This installer still has an unfinished manifest URL. Alex must configure and rebuild the public package first."
}

if (-not $CockatriceDataDir) {
    if ($settings -and $settings.PSObject.Properties.Name -contains "cockatrice_data_dir" -and $settings.cockatrice_data_dir) {
        $CockatriceDataDir = [string]$settings.cockatrice_data_dir
    } else {
        $CockatriceDataDir = Join-Path $env:LOCALAPPDATA "Cockatrice\Cockatrice"
    }
}
$customSetsDir = Join-Path $CockatriceDataDir "customsets"
New-Item -ItemType Directory -Path $customSetsDir -Force | Out-Null

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Step "Checking the hosted manifest..."
$manifestText = (Invoke-WebRequest -UseBasicParsing -Uri $ManifestUrl -TimeoutSec 30).Content
$manifest = $manifestText | ConvertFrom-Json
if (-not ($manifest.PSObject.Properties.Name -contains "schema_version") -or [int]$manifest.schema_version -ne 1) {
    throw "Unsupported manifest schema."
}
if ([string]$manifest.package_id -ne "alex-cockatrice-alt-art") {
    throw "The hosted manifest belongs to a different package."
}
if (-not ($manifest.PSObject.Properties.Name -contains "cockatrice_xml")) {
    throw "The manifest has no Cockatrice XML entry."
}
$xmlInfo = $manifest.cockatrice_xml
$installFilename = [string]$xmlInfo.install_filename
if (-not $installFilename -or [IO.Path]::GetFileName($installFilename) -ne $installFilename -or -not $installFilename.EndsWith(".xml")) {
    throw "The manifest contains an unsafe XML filename."
}
$expectedHash = ([string]$xmlInfo.sha256).ToLowerInvariant()
if ($expectedHash -notmatch "^[0-9a-f]{64}$") {
    throw "The manifest contains an invalid XML SHA-256."
}
$xmlUrl = [string]$xmlInfo.url
if (-not [Uri]::IsWellFormedUriString($xmlUrl, [UriKind]::Absolute)) {
    $xmlUrl = ([Uri]::new([Uri]$ManifestUrl, [string]$xmlInfo.path)).AbsoluteUri
}

$stagingPath = Join-Path $customSetsDir ("." + [Guid]::NewGuid().ToString("N") + ".xml.download")
try {
    Write-Step "Downloading and verifying the custom-set XML..."
    Invoke-WebRequest -UseBasicParsing -Uri $xmlUrl -OutFile $stagingPath -TimeoutSec 60
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $stagingPath).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Downloaded XML failed SHA-256 verification. No installed file was changed."
    }
    [xml]$xmlDocument = Get-Content -LiteralPath $stagingPath -Raw -Encoding UTF8
    if ($xmlDocument.DocumentElement.Name -ne "cockatrice_carddatabase" -or [string]$xmlDocument.DocumentElement.version -ne "4") {
        throw "Downloaded XML is not a Cockatrice v4 card database."
    }

    $destination = Join-Path $customSetsDir $installFilename
    $alreadyCurrent = $false
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $installedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($installedHash -eq $expectedHash) {
            $alreadyCurrent = $true
        } else {
            $backupDir = Join-Path $installRoot "backups"
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            Copy-Item -LiteralPath $destination -Destination (Join-Path $backupDir "$installFilename.$stamp.bak") -Force
        }
    }
    if ($alreadyCurrent) {
        Remove-Item -LiteralPath $stagingPath -Force
        Write-Step "Already current (version $($manifest.version))."
    } else {
        Move-Item -LiteralPath $stagingPath -Destination $destination -Force
        Write-Step "Installed version $($manifest.version) to $destination"
    }
} finally {
    Remove-Item -LiteralPath $stagingPath -Force -ErrorAction SilentlyContinue
}

$state = [ordered]@{
    schema_version = 1
    package_id = "alex-cockatrice-alt-art"
    version = [string]$manifest.version
    manifest_url = $ManifestUrl
    installed_xml = (Join-Path $customSetsDir $installFilename)
    xml_sha256 = $expectedHash
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
}
$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8

if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
    $newSettings = [ordered]@{
        manifest_url = $ManifestUrl
        cockatrice_data_dir = $CockatriceDataDir
        cockatrice_exe = $CockatriceExe
    }
    $newSettings | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $settingsPath -Encoding UTF8
}

$resolvedExe = Find-CockatriceExe $CockatriceExe $settings
if ($InstallShortcut) {
    New-LaunchShortcut $installRoot $resolvedExe
}
if ($NoLaunch) {
    Write-Step "Update complete; launch was disabled for this test run."
    exit 0
}
if (Get-Process -Name "Cockatrice" -ErrorAction SilentlyContinue) {
    Write-Step "Cockatrice is already open. Restart it to load the updated XML."
    exit 0
}
if ($resolvedExe) {
    Write-Step "Launching Cockatrice..."
    Start-Process -FilePath $resolvedExe
} else {
    Write-Step "Update complete. Cockatrice.exe was not auto-detected, so open Cockatrice manually."
    Write-Host "For a portable/custom install, put its full path in: $settingsPath" -ForegroundColor Yellow
}

