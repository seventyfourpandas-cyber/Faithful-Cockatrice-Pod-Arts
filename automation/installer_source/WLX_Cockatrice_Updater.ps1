[CmdletBinding()]
param(
    [string]$ManifestUrl = "",
    [string]$CockatriceDataDir = "",
    [string]$CockatricePicsDir = "",
    [string]$CockatriceNetworkCacheDir = "",
    [string]$CockatriceExe = "",
    [switch]$NoLaunch,
    [switch]$InstallShortcut,
    [switch]$RepairPictures,
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ShortcutIconName = "WLX_Shortcut.ico"
$ShortcutIconSha256 = "__SHORTCUT_ICON_SHA256__"
$ShortcutIconBase64 = @'
__SHORTCUT_ICON_BASE64__
'@

function Write-Step([string]$Message) {
    Write-Host "[WLX] $Message" -ForegroundColor Cyan
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

function Install-ShortcutIcon([string]$InstallRoot) {
    $iconPath = Join-Path $InstallRoot $ShortcutIconName
    if (Test-Path -LiteralPath $iconPath -PathType Leaf) {
        $installedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $iconPath).Hash.ToLowerInvariant()
        if ($installedHash -eq $ShortcutIconSha256) { return $iconPath }
    }

    try {
        $iconBytes = [Convert]::FromBase64String(($ShortcutIconBase64 -replace '\s', ''))
    } catch {
        throw "The embedded WLX shortcut icon is invalid."
    }
    $temporaryIcon = "$iconPath.pending-$([Guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllBytes($temporaryIcon, $iconBytes)
        $writtenHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporaryIcon).Hash.ToLowerInvariant()
        if ($writtenHash -ne $ShortcutIconSha256) {
            throw "The embedded WLX shortcut icon failed SHA-256 verification."
        }
        Move-Item -LiteralPath $temporaryIcon -Destination $iconPath -Force
    } finally {
        Remove-Item -LiteralPath $temporaryIcon -Force -ErrorAction SilentlyContinue
    }
    return $iconPath
}

function Read-XmlFile([string]$Path) {
    try {
        [xml]$document = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        return $document
    } catch {
        throw "Could not parse Cockatrice XML '$Path': $($_.Exception.Message)"
    }
}

function Get-XmlText($XmlDocument, [string]$XPath) {
    $node = $XmlDocument.SelectSingleNode($XPath)
    if ($null -eq $node) { return "" }
    return [string]$node.InnerText
}

function Get-PrintingIdentities($XmlDocument) {
    $identities = @()
    foreach ($card in @($XmlDocument.SelectNodes("/cockatrice_carddatabase/cards/card"))) {
        $nameNode = $card.SelectSingleNode("name")
        if ($null -eq $nameNode) { continue }
        $officialName = [string]$nameNode.InnerText
        foreach ($printing in @($card.SelectNodes("set"))) {
            $uuidAttribute = $printing.Attributes["uuid"]
            $numberAttribute = $printing.Attributes["num"]
            $flavorAttribute = $printing.Attributes["flavorName"]
            $pictureAttribute = $printing.Attributes["picurl"]
            $identities += [pscustomobject]@{
                official_name = $officialName
                set_code = [string]$printing.InnerText
                collector_number = if ($null -ne $numberAttribute) { [string]$numberAttribute.Value } else { "" }
                uuid = if ($null -ne $uuidAttribute) { [string]$uuidAttribute.Value } else { "" }
                flavor_name = if ($null -ne $flavorAttribute) { [string]$flavorAttribute.Value } else { "" }
                picture_url = if ($null -ne $pictureAttribute) { [string]$pictureAttribute.Value } else { "" }
            }
        }
    }
    return $identities
}

function Get-IdentityKey($Identity) {
    return (([string]$Identity.official_name).Trim() + "|" +
        ([string]$Identity.set_code).Trim() + "|" +
        ([string]$Identity.collector_number).Trim()).ToLowerInvariant()
}

function Get-ChangedPictureIdentities($PreviousIdentities, $CurrentIdentities) {
    # Return both sides of any identity whose card name or content-addressed
    # picture URL changed.  Keeping the UUID stable preserves saved decks, while
    # clearing its narrowly matched filesystem cache makes Cockatrice fetch the
    # replacement artwork.
    $previousByUuid = @{}
    $previousByKey = @{}
    foreach ($identity in @($PreviousIdentities)) {
        if ($identity.uuid) {
            $previousByUuid[([string]$identity.uuid).ToLowerInvariant()] = $identity
        }
        $previousByKey[(Get-IdentityKey $identity)] = $identity
    }

    $changed = @()
    $matchedPreviousUuids = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $matchedPreviousKeys = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($current in @($CurrentIdentities)) {
        $previous = $null
        if ($current.uuid) {
            $uuidKey = ([string]$current.uuid).ToLowerInvariant()
            if ($previousByUuid.ContainsKey($uuidKey)) { $previous = $previousByUuid[$uuidKey] }
        }
        if ($null -eq $previous) {
            $identityKey = Get-IdentityKey $current
            if ($previousByKey.ContainsKey($identityKey)) { $previous = $previousByKey[$identityKey] }
        }
        if ($null -eq $previous) { continue }
        if ($previous.uuid) { $matchedPreviousUuids.Add([string]$previous.uuid) | Out-Null }
        $matchedPreviousKeys.Add((Get-IdentityKey $previous)) | Out-Null

        $nameChanged = -not [StringComparer]::OrdinalIgnoreCase.Equals(
            ([string]$previous.official_name).Trim(),
            ([string]$current.official_name).Trim()
        )
        $urlChanged = -not [StringComparer]::Ordinal.Equals(
            ([string]$previous.picture_url).Trim(),
            ([string]$current.picture_url).Trim()
        )
        if ($nameChanged -or $urlChanged) {
            $changed += $previous
            $changed += $current
        }
    }

    # A removed printing can leave a stale filesystem picture behind.  Include
    # its old identity so that entry is recoverably quarantined on update.
    foreach ($previous in @($PreviousIdentities)) {
        $wasMatched = $false
        if ($previous.uuid -and $matchedPreviousUuids.Contains([string]$previous.uuid)) {
            $wasMatched = $true
        } elseif ($matchedPreviousKeys.Contains((Get-IdentityKey $previous))) {
            $wasMatched = $true
        }
        if (-not $wasMatched) { $changed += $previous }
    }
    return $changed
}

function Test-PackDuplicate(
    $CandidateXml,
    $CurrentIdentities,
    $LegacyIdentities,
    [string]$CurrentSourceUrl,
    [string]$CurrentAuthor
) {
    $candidateSource = (Get-XmlText $CandidateXml "/cockatrice_carddatabase/info/sourceUrl").Trim().TrimEnd("/")
    $expectedSource = $CurrentSourceUrl.Trim().TrimEnd("/")
    if ($candidateSource -and $expectedSource -and
        [StringComparer]::OrdinalIgnoreCase.Equals($candidateSource, $expectedSource)) {
        return $true
    }

    $currentUuids = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $currentKeys = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $recognizedIdentities = @($CurrentIdentities) + @($LegacyIdentities)
    foreach ($identity in $recognizedIdentities) {
        if ($identity.uuid) { $currentUuids.Add([string]$identity.uuid) | Out-Null }
        $currentKeys.Add((Get-IdentityKey $identity)) | Out-Null
    }

    $identityOverlap = $false
    foreach ($identity in @(Get-PrintingIdentities $CandidateXml)) {
        if ($identity.uuid -and $currentUuids.Contains([string]$identity.uuid)) {
            return $true
        }
        if ($currentKeys.Contains((Get-IdentityKey $identity))) {
            $identityOverlap = $true
        }
    }

    $candidateAuthor = (Get-XmlText $CandidateXml "/cockatrice_carddatabase/info/author").Trim()
    return ($identityOverlap -and $candidateAuthor -and $CurrentAuthor -and
        [StringComparer]::OrdinalIgnoreCase.Equals($candidateAuthor, $CurrentAuthor.Trim()))
}

function Move-QuarantineFile(
    [string]$Path,
    [string]$InstallRoot,
    [string]$Stamp,
    [string]$Category,
    [string]$RelativePath = ""
) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return "" }
    if (-not $RelativePath) { $RelativePath = Split-Path -Leaf $Path }
    $destination = Join-Path (Join-Path (Join-Path $InstallRoot "quarantine") $Stamp) (Join-Path $Category $RelativePath)
    $parent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    if (Test-Path -LiteralPath $destination) {
        $destination = Join-Path $parent (([Guid]::NewGuid().ToString("N")) + "-" + (Split-Path -Leaf $RelativePath))
    }
    Move-Item -LiteralPath $Path -Destination $destination
    return $destination
}

function ConvertTo-CockatriceFileName([string]$Name) {
    $value = $Name -replace ' // ', ''
    $value = $value -replace '[*<>:"\\?\x00-\x08\x10-\x1f]', ''
    $value = $value -replace '[/\x09-\x0f]', ' '
    return $value
}

function ConvertTo-CockatriceSetFolder([string]$SetCode) {
    $reserved = @("CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9")
    if ($reserved -contains $SetCode.ToUpperInvariant()) { return $SetCode + "_" }
    return $SetCode
}

function Get-CacheBaseNames($Identities, [switch]$IncludeNameOnly) {
    $names = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($identity in @($Identities)) {
        $name = ConvertTo-CockatriceFileName ([string]$identity.official_name)
        $setCode = ConvertTo-CockatriceSetFolder ([string]$identity.set_code)
        $collector = [string]$identity.collector_number
        $providerId = [string]$identity.uuid
        foreach ($separator in @("_", "-")) {
            if ($providerId) { $names.Add($name + $separator + $providerId) | Out-Null }
            if ($setCode -and $collector) {
                $names.Add($name + $separator + $setCode + $separator + $collector) | Out-Null
                $names.Add($setCode + $separator + $collector + $separator + $name) | Out-Null
            }
            if ($setCode) { $names.Add($name + $separator + $setCode) | Out-Null }
        }
        if ($IncludeNameOnly) { $names.Add($name) | Out-Null }
    }
    return ,$names
}

function Find-CockatricePicsDir([string]$Explicit, [string]$DataDir, $Settings) {
    if ($Explicit) { return [Environment]::ExpandEnvironmentVariables($Explicit) }
    if ($Settings -and $Settings.PSObject.Properties.Name -contains "cockatrice_pics_dir" -and $Settings.cockatrice_pics_dir) {
        return [Environment]::ExpandEnvironmentVariables([string]$Settings.cockatrice_pics_dir)
    }

    $pathsIni = Join-Path $DataDir "settings\paths.ini"
    if (Test-Path -LiteralPath $pathsIni -PathType Leaf) {
        $insidePaths = $false
        foreach ($line in Get-Content -LiteralPath $pathsIni -Encoding UTF8) {
            if ($line -match '^\s*\[(.+)\]\s*$') {
                $insidePaths = ([string]$Matches[1]).Trim() -eq "paths"
                continue
            }
            if ($insidePaths -and $line -match '^\s*pics\s*=(.*)$') {
                $value = ([string]$Matches[1]).Trim().Trim('"')
                if ($value) {
                    $value = $value.Replace('\\', '\')
                    return [Environment]::ExpandEnvironmentVariables($value)
                }
            }
        }
    }
    return Join-Path $DataDir "pics"
}

function Find-CockatriceNetworkCacheDir([string]$Explicit, [string]$DataDir, $Settings) {
    if ($Explicit) { return [Environment]::ExpandEnvironmentVariables($Explicit) }
    if ($Settings -and $Settings.PSObject.Properties.Name -contains "cockatrice_network_cache_dir" -and $Settings.cockatrice_network_cache_dir) {
        return [Environment]::ExpandEnvironmentVariables([string]$Settings.cockatrice_network_cache_dir)
    }
    return Join-Path $DataDir "cache\downloaded"
}

function Repair-FilesystemPictureCache(
    [string]$PicsDir,
    $Identities,
    [string]$InstallRoot,
    [string]$Stamp,
    [switch]$IncludeNameOnly
) {
    $downloadedRoot = Join-Path $PicsDir "downloadedPics"
    if (-not (Test-Path -LiteralPath $downloadedRoot -PathType Container)) { return @() }
    $baseNames = Get-CacheBaseNames $Identities -IncludeNameOnly:$IncludeNameOnly
    $moved = @()
    foreach ($file in Get-ChildItem -LiteralPath $downloadedRoot -File -Recurse -ErrorAction SilentlyContinue) {
        if ($file.Extension.ToLowerInvariant() -notin @(".png", ".jpg", ".jpeg", ".webp", ".avif")) { continue }
        if (-not $baseNames.Contains($file.BaseName)) { continue }
        $relative = $file.FullName.Substring($downloadedRoot.Length)
        while ($relative.StartsWith("\") -or $relative.StartsWith("/")) { $relative = $relative.Substring(1) }
        $target = Move-QuarantineFile $file.FullName $InstallRoot $Stamp "pictures-filesystem" $relative
        if ($target) { $moved += $target }
    }
    return $moved
}

function Move-NetworkPictureCache([string]$CacheDir, [string]$InstallRoot, [string]$Stamp) {
    if (-not (Test-Path -LiteralPath $CacheDir -PathType Container)) { return "" }
    if ((Split-Path -Leaf $CacheDir) -ne "downloaded") {
        throw "Refusing to quarantine a network cache whose final folder is not named 'downloaded': $CacheDir"
    }
    $destinationRoot = Join-Path (Join-Path (Join-Path $InstallRoot "quarantine") $Stamp) "pictures-network"
    New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
    $destination = Join-Path $destinationRoot "downloaded"
    if (Test-Path -LiteralPath $destination) {
        $destination = Join-Path $destinationRoot ("downloaded-" + [Guid]::NewGuid().ToString("N"))
    }
    Move-Item -LiteralPath $CacheDir -Destination $destination
    return $destination
}

function Find-CockatriceExe([string]$Explicit, $Settings) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Explicit) { $candidates.Add($Explicit) }
    if ($Settings -and $Settings.PSObject.Properties.Name -contains "cockatrice_exe" -and $Settings.cockatrice_exe) {
        $candidates.Add([string]$Settings.cockatrice_exe)
    }
    if ($env:ProgramFiles) { $candidates.Add((Join-Path $env:ProgramFiles "Cockatrice\Cockatrice.exe")) }
    if (${env:ProgramFiles(x86)}) { $candidates.Add((Join-Path ${env:ProgramFiles(x86)} "Cockatrice\Cockatrice.exe")) }
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

function Get-LaunchShortcutPath() {
    $desktop = [Environment]::GetFolderPath("Desktop")
    if (-not $desktop) { return "" }
    return (Join-Path $desktop "__DISPLAY_NAME__.lnk")
}

function New-LaunchShortcut([string]$InstallRoot, [string]$IconPath, [string]$ExePath) {
    $shortcutPath = Get-LaunchShortcutPath
    if (-not $shortcutPath) { return }
    $batchPath = Join-Path $InstallRoot "UPDATE_AND_LAUNCH.bat"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $env:ComSpec
    $shortcut.Arguments = "/c `"`"$batchPath`"`""
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.Description = "Update __DISPLAY_NAME__ and launch Cockatrice"
    if ($IconPath -and (Test-Path -LiteralPath $IconPath -PathType Leaf)) {
        $shortcut.IconLocation = "$IconPath,0"
    } elseif ($ExePath) {
        $shortcut.IconLocation = "$ExePath,0"
    }
    $shortcut.Save()
    Write-Step "Desktop shortcut created: $shortcutPath"
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$config = Read-JsonFile (Join-Path $scriptRoot "installer_config.json")
if ([string]$config.package_id -ne "__PACKAGE_ID__") {
    throw "The installer configuration belongs to a different package."
}
$legacyIdentities = @()
if ($config.PSObject.Properties.Name -contains "legacy_printings") {
    foreach ($legacy in @($config.legacy_printings)) {
        $fields = @($legacy.PSObject.Properties.Name)
        if (
            $fields -contains "official_name" -and
            $fields -contains "set_code" -and
            $fields -contains "collector_number" -and
            $fields -contains "uuid"
        ) {
            $legacyIdentities += [pscustomobject]@{
                official_name = [string]$legacy.official_name
                set_code = [string]$legacy.set_code
                collector_number = [string]$legacy.collector_number
                uuid = [string]$legacy.uuid
                flavor_name = ""
                picture_url = ""
            }
        }
    }
}

if (-not $env:LOCALAPPDATA) { throw "Windows LOCALAPPDATA is unavailable." }
$installRoot = Join-Path $env:LOCALAPPDATA ([string]$config.install_folder)
New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
$settingsPath = Join-Path $installRoot "installer_settings.json"
$legacySettingsPath = Join-Path $installRoot "friend_settings.json"
$statePath = Join-Path $installRoot "installed_state.json"
$reportPath = Join-Path $installRoot "last_migration_report.json"
$settings = $null
if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
    $settings = Read-JsonFile $settingsPath
} elseif (Test-Path -LiteralPath $legacySettingsPath -PathType Leaf) {
    $settings = Read-JsonFile $legacySettingsPath
}

if ($RepairPictures -and (Get-Process -Name "Cockatrice" -ErrorAction SilentlyContinue)) {
    throw "Close Cockatrice before running picture repair, then try again."
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
                Move-Item -LiteralPath $installedXml -Destination (Join-Path $removedDir $removedName)
                Write-Step "The XML was moved to $removedDir and can be recovered."
            }
        }
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    }
    $shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "__DISPLAY_NAME__.lnk"
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
    throw "This installer still has an unfinished manifest URL. The publisher must configure and rebuild the public package first."
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
$picsDir = Find-CockatricePicsDir $CockatricePicsDir $CockatriceDataDir $settings
$networkCacheDir = Find-CockatriceNetworkCacheDir $CockatriceNetworkCacheDir $CockatriceDataDir $settings

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Step "Checking the hosted manifest..."
$manifestText = (Invoke-WebRequest -UseBasicParsing -Uri $ManifestUrl -TimeoutSec 30).Content
$manifest = $manifestText | ConvertFrom-Json
if (-not ($manifest.PSObject.Properties.Name -contains "schema_version") -or [int]$manifest.schema_version -ne 1) {
    throw "Unsupported manifest schema."
}
if ([string]$manifest.package_id -ne "__PACKAGE_ID__") { throw "The hosted manifest belongs to a different package." }
if ($manifest.PSObject.Properties.Name -contains "release_ready" -and -not [bool]$manifest.release_ready) {
    throw "The hosted release is marked unfinished; nothing was installed."
}
if (-not ($manifest.PSObject.Properties.Name -contains "cockatrice_xml")) { throw "The manifest has no Cockatrice XML entry." }
$xmlInfo = $manifest.cockatrice_xml
$installFilename = [string]$xmlInfo.install_filename
if (-not $installFilename -or [IO.Path]::GetFileName($installFilename) -ne $installFilename -or -not $installFilename.EndsWith(".xml")) {
    throw "The manifest contains an unsafe XML filename."
}
$expectedHash = ([string]$xmlInfo.sha256).ToLowerInvariant()
if ($expectedHash -notmatch "^[0-9a-f]{64}$") { throw "The manifest contains an invalid XML SHA-256." }
$xmlUrl = [string]$xmlInfo.url
if (-not [Uri]::IsWellFormedUriString($xmlUrl, [UriKind]::Absolute)) {
    $xmlUrl = ([Uri]::new([Uri]$ManifestUrl, [string]$xmlInfo.path)).AbsoluteUri
}

$stagingPath = Join-Path $customSetsDir ("." + [Guid]::NewGuid().ToString("N") + ".xml.download")
$quarantineStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$quarantinedXml = @()
$duplicateIdentities = @()
$quarantinedPictures = @()
$networkCacheQuarantined = ""
$destination = Join-Path $customSetsDir $installFilename
$previousIdentities = @()
if (Test-Path -LiteralPath $destination -PathType Leaf) {
    try {
        $previousIdentities = @(Get-PrintingIdentities (Read-XmlFile $destination))
    } catch {
        Write-Host "[WLX] The previous canonical XML could not be read for picture-change detection." -ForegroundColor DarkYellow
    }
}
$changedPictureIdentities = @()
try {
    Write-Step "Downloading and verifying the custom-set XML..."
    Invoke-WebRequest -UseBasicParsing -Uri $xmlUrl -OutFile $stagingPath -TimeoutSec 60
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $stagingPath).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) { throw "Downloaded XML failed SHA-256 verification. No installed file was changed." }
    $xmlDocument = Read-XmlFile $stagingPath
    if ($xmlDocument.DocumentElement.Name -ne "cockatrice_carddatabase" -or [string]$xmlDocument.DocumentElement.version -ne "4") {
        throw "Downloaded XML is not a Cockatrice v4 card database."
    }

    $currentIdentities = @(Get-PrintingIdentities $xmlDocument)
    if ($currentIdentities.Count -lt 1) { throw "Downloaded XML contains no card printings." }
    $changedPictureIdentities = @(Get-ChangedPictureIdentities $previousIdentities $currentIdentities)
    $currentSourceUrl = Get-XmlText $xmlDocument "/cockatrice_carddatabase/info/sourceUrl"
    $currentAuthor = Get-XmlText $xmlDocument "/cockatrice_carddatabase/info/author"

    Write-Step "Checking for numbered or duplicate ghost XML files..."
    foreach ($candidate in Get-ChildItem -LiteralPath $customSetsDir -Filter "*.xml" -File -ErrorAction SilentlyContinue) {
        if ([StringComparer]::OrdinalIgnoreCase.Equals($candidate.FullName, $destination)) { continue }
        try {
            $candidateXml = Read-XmlFile $candidate.FullName
        } catch {
            Write-Host "[WLX] Ignoring unrelated/unreadable XML: $($candidate.Name)" -ForegroundColor DarkYellow
            continue
        }
        if (Test-PackDuplicate $candidateXml $currentIdentities $legacyIdentities $currentSourceUrl $currentAuthor) {
            $duplicateIdentities += @(Get-PrintingIdentities $candidateXml)
            $target = Move-QuarantineFile $candidate.FullName $installRoot $quarantineStamp "customsets"
            if ($target) {
                $quarantinedXml += $target
                Write-Step "Quarantined duplicate XML: $($candidate.Name)"
            }
        }
    }

    $alreadyCurrent = $false
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $installedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($installedHash -eq $expectedHash) {
            $alreadyCurrent = $true
        } else {
            $backupDir = Join-Path $installRoot "backups"
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
            $backupStamp = Get-Date -Format "yyyyMMdd-HHmmssfff"
            Copy-Item -LiteralPath $destination -Destination (Join-Path $backupDir "$installFilename.$backupStamp.bak")
        }
    }
    if ($alreadyCurrent) {
        Remove-Item -LiteralPath $stagingPath -Force
        Write-Step "Canonical XML is already current (version $($manifest.version))."
    } else {
        Move-Item -LiteralPath $stagingPath -Destination $destination -Force
        Write-Step "Installed one canonical XML: $destination"
    }

    $cacheIdentities = @($currentIdentities) + @($legacyIdentities) + @($duplicateIdentities)
    if ($quarantinedXml.Count -gt 0) {
        $quarantinedPictures += @(Repair-FilesystemPictureCache $picsDir $cacheIdentities $installRoot $quarantineStamp)
    }
    if ($changedPictureIdentities.Count -gt 0) {
        Write-Step "Printing or artwork changes detected; refreshing only the matching Cockatrice picture cache entries..."
        $quarantinedPictures += @(Repair-FilesystemPictureCache $picsDir $changedPictureIdentities $installRoot $quarantineStamp)
    }
    if ($RepairPictures) {
        Write-Step "Running recoverable picture-cache repair..."
        $quarantinedPictures += @(Repair-FilesystemPictureCache $picsDir $cacheIdentities $installRoot $quarantineStamp -IncludeNameOnly)
        $networkCacheQuarantined = Move-NetworkPictureCache $networkCacheDir $installRoot $quarantineStamp
    }
} finally {
    Remove-Item -LiteralPath $stagingPath -Force -ErrorAction SilentlyContinue
}

$identityState = @()
foreach ($identity in @($currentIdentities)) {
    $identityState += [ordered]@{
        official_name = [string]$identity.official_name
        set_code = [string]$identity.set_code
        collector_number = [string]$identity.collector_number
        uuid = [string]$identity.uuid
        picture_url = [string]$identity.picture_url
    }
}
$state = [ordered]@{
    schema_version = 2
    package_id = "__PACKAGE_ID__"
    version = [string]$manifest.version
    manifest_url = $ManifestUrl
    installed_xml = $destination
    xml_sha256 = $expectedHash
    printings = $identityState
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
}
$state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8

$migrationReport = [ordered]@{
    schema_version = 1
    package_id = "__PACKAGE_ID__"
    version = [string]$manifest.version
    canonical_xml = $destination
    quarantined_xml = @($quarantinedXml)
    quarantined_filesystem_pictures = @($quarantinedPictures)
    quarantined_network_cache = $networkCacheQuarantined
    picture_repair_requested = [bool]$RepairPictures
    picture_cache_identities_refreshed = [int]$changedPictureIdentities.Count
    legacy_printings_recognized = @($legacyIdentities)
    completed_at = (Get-Date).ToUniversalTime().ToString("o")
}
$migrationReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8

if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
    $newSettings = [ordered]@{
        manifest_url = $ManifestUrl
        cockatrice_data_dir = $CockatriceDataDir
        cockatrice_pics_dir = ""
        cockatrice_network_cache_dir = ""
        cockatrice_exe = $CockatriceExe
    }
    $newSettings | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $settingsPath -Encoding UTF8
}

if ($quarantinedXml.Count -gt 0) {
    Write-Step "Ghost cleanup complete: $($quarantinedXml.Count) duplicate XML file(s) quarantined."
}
if ($quarantinedPictures.Count -gt 0) {
    Write-Step "Moved $($quarantinedPictures.Count) matching cached picture(s) into recoverable quarantine."
}
if ($networkCacheQuarantined) {
    Write-Step "Moved Cockatrice's network image cache into recoverable quarantine; images will redownload as needed."
}

$resolvedExe = Find-CockatriceExe $CockatriceExe $settings
$shortcutIcon = Install-ShortcutIcon $installRoot
$existingShortcut = Get-LaunchShortcutPath
if ($InstallShortcut -or ($existingShortcut -and (Test-Path -LiteralPath $existingShortcut -PathType Leaf))) {
    New-LaunchShortcut $installRoot $shortcutIcon $resolvedExe
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
