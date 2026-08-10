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

$script:LauncherWindow = $null
$script:LauncherFeed = New-Object System.Collections.Generic.List[string]
$script:LauncherProgressValue = 0
$script:LauncherLogPath = ""
$script:LauncherUiEnabled = (
    $env:OS -eq "Windows_NT" -and
    -not $NoLaunch -and
    -not $InstallShortcut -and
    -not $RepairPictures -and
    -not $Uninstall
)

function Invoke-LauncherPump() {
    if ($null -eq $script:LauncherWindow) { return }
    try {
        $script:LauncherWindow.Dispatcher.Invoke(
            [action]{},
            [System.Windows.Threading.DispatcherPriority]::Background
        )
    } catch { }
}

function Set-LauncherStatus([string]$Status) {
    if ($null -eq $script:LauncherWindow -or -not $Status) { return }
    $script:LauncherStatus.Text = $Status.ToUpperInvariant()
    Invoke-LauncherPump
}

function Add-LauncherActivity([string]$Message) {
    if ($null -eq $script:LauncherWindow -or -not $Message) { return }
    [void]$script:LauncherFeed.Add($Message)
    while ($script:LauncherFeed.Count -gt 3) { $script:LauncherFeed.RemoveAt(0) }
    $lines = @($script:LauncherFeed)
    while ($lines.Count -lt 3) { $lines = @(("")) + $lines }
    $script:LauncherFeed1.Text = [string]$lines[$lines.Count - 3]
    $script:LauncherFeed2.Text = [string]$lines[$lines.Count - 2]
    $script:LauncherFeed3.Text = [string]$lines[$lines.Count - 1]
    Invoke-LauncherPump
}

function Set-LauncherProgress([int]$Value) {
    if ($null -eq $script:LauncherWindow) { return }
    $target = [Math]::Max(0, [Math]::Min(100, $Value))
    $start = $script:LauncherProgressValue
    if ($target -lt $start) { $start = $target }
    $steps = if ($target -eq $start) { 1 } else { 8 }
    for ($index = 1; $index -le $steps; $index++) {
        $current = $start + (($target - $start) * $index / $steps)
        $width = 6.0 * $current
        $script:LauncherProgressClip.Rect = New-Object System.Windows.Rect -ArgumentList 0, 0, $width, 62
        $script:LauncherEchoClip.Rect = New-Object System.Windows.Rect -ArgumentList 0, 0, $width, 62
        Invoke-LauncherPump
        if ($steps -gt 1) { Start-Sleep -Milliseconds 12 }
    }
    $script:LauncherProgressValue = $target
}

function Initialize-LauncherWindow([string]$Version, [string]$InstallRoot) {
    if (-not $script:LauncherUiEnabled) { return }
    try {
        Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
        $xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="__DISPLAY_NAME__"
        Width="760" Height="500" WindowStartupLocation="CenterScreen"
        WindowStyle="None" ResizeMode="NoResize" AllowsTransparency="True"
        Background="Transparent" ShowInTaskbar="True">
  <Border x:Name="LauncherShell" CornerRadius="14" BorderThickness="1" BorderBrush="#303841">
    <Border.Effect>
      <DropShadowEffect BlurRadius="28" ShadowDepth="12" Opacity="0.42" Color="#000000"/>
    </Border.Effect>
    <Border.Background>
      <LinearGradientBrush StartPoint="0,0" EndPoint="1,1">
        <GradientStop Color="#0B0E11" Offset="0"/>
        <GradientStop Color="#11161B" Offset="1"/>
      </LinearGradientBrush>
    </Border.Background>
    <Viewbox Stretch="Fill">
      <Canvas Width="760" Height="500" ClipToBounds="True">
        <Ellipse Canvas.Left="363" Canvas.Top="34" Width="34" Height="34" Stroke="#FFE08A" StrokeThickness="1"/>
        <Path Stroke="#FFE08A" StrokeThickness="1" Data="M 380,17 L 380,35 M 380,68 L 380,86 M 346,51 L 364,51 M 396,51 L 414,51 M 356,27 L 368,39 M 392,63 L 404,75 M 404,27 L 392,39 M 368,63 L 356,75 M 301,51 L 335,51 M 425,51 L 459,51"/>

        <Path Stroke="#5BB6FF" StrokeThickness="1" Opacity="0.90" Data="M 475,104 C 537,56 605,131 653,79 C 685,45 719,46 742,47 M 512,134 C 567,83 627,176 688,112 C 705,94 724,87 743,84"/>
        <Path Stroke="#5BB6FF" StrokeThickness="1" Opacity="0.75" StrokeDashArray="2,5" Data="M 525,119 C 581,119 613,86 654,108 C 693,129 713,143 743,139"/>
        <Path Stroke="#5BB6FF" StrokeThickness="1" Opacity="0.9" Data="M 649,80 L 653,76 L 657,80 L 653,84 Z M 684,112 L 688,108 L 692,112 L 688,116 Z M 521,119 L 525,115 L 529,119 L 525,123 Z"/>

        <Path Stroke="#59636D" StrokeThickness="1" Opacity="0.63" Data="M 0,311 L 38,314 L 51,325 L 83,329 L 93,343 L 131,355 L 139,371 L 181,383 L 200,404 L 255,419 M 0,322 L 31,325 L 48,337 L 78,342 L 94,356 L 127,367 L 138,384 L 183,399 L 200,417 L 248,432 M 760,302 L 716,306 L 706,317 L 676,322 L 664,335 L 628,347 L 620,363 L 577,377 L 559,397 L 507,414 M 760,316 L 724,320 L 710,333 L 682,337 L 667,352 L 636,361 L 623,379 L 580,393 L 561,412 L 515,426"/>
        <Path Stroke="#59636D" StrokeThickness="1" Opacity="0.48" StrokeDashArray="2,5" Data="M 0,337 L 28,340 L 40,350 L 67,355 L 79,368 L 110,378 L 119,393 L 157,407 L 172,425 L 217,439 M 760,331 L 729,334 L 717,345 L 691,350 L 680,363 L 651,373 L 641,388 L 604,402 L 588,420 L 545,433"/>

        <Path Stroke="#54D181" StrokeThickness="1" Opacity="0.88" Data="M 31,459 L 173,459 L 191,441 M 31,459 L 31,373 M 31,398 L 12,379 M 31,421 L 51,401 M 76,459 L 76,410 M 76,429 L 60,413 M 76,439 L 94,422 M 12,379 L 5,367 L 9,362 L 18,373 Z M 51,401 L 53,387 L 60,384 L 58,397 Z M 60,413 L 58,400 L 51,397 L 52,409 Z M 94,422 L 96,408 L 103,405 L 101,418 Z"/>
        <Path Stroke="#54D181" StrokeThickness="1" Opacity="0.88" Data="M 729,459 L 587,459 L 569,441 M 729,459 L 729,373 M 729,398 L 748,379 M 729,421 L 709,401 M 684,459 L 684,410 M 684,429 L 700,413 M 684,439 L 666,422 M 748,379 L 755,367 L 751,362 L 742,373 Z M 709,401 L 707,387 L 700,384 L 702,397 Z M 700,413 L 702,400 L 709,397 L 708,409 Z M 666,422 L 664,408 L 657,405 L 659,418 Z"/>

        <Canvas Canvas.Left="28" Canvas.Top="24" Width="48" Height="48">
          <Path Stroke="#E9EEF2" StrokeThickness="1.45" StrokeStartLineCap="Square" StrokeEndLineCap="Square" StrokeLineJoin="Miter" Data="M 8,44 L 24,4 L 40,44 M 3,17 L 17,33 L 24,23 L 31,33 L 45,17"/>
        </Canvas>
        <Rectangle Canvas.Left="90" Canvas.Top="29" Width="1" Height="38" Fill="#303841"/>
        <TextBlock Canvas.Left="105" Canvas.Top="28" Foreground="#E9EEF2" FontFamily="Segoe UI" FontSize="11.5" FontWeight="Medium" Text="WILLEX'S WHIMSICAL ARTS"/>
        <TextBlock Canvas.Left="105" Canvas.Top="48" Foreground="#7F8B96" FontFamily="Segoe UI" FontSize="8.8" Text="COCKATRICE COLLECTION LAUNCHER"/>

        <TextBlock x:Name="FeedLine1" Canvas.Left="68" Canvas.Top="178" Width="390" Height="22" Foreground="#56616B" FontFamily="Consolas" FontSize="11.5"/>
        <TextBlock x:Name="FeedLine2" Canvas.Left="68" Canvas.Top="202" Width="390" Height="22" Foreground="#89949E" FontFamily="Consolas" FontSize="11.5"/>
        <TextBlock x:Name="FeedLine3" Canvas.Left="68" Canvas.Top="226" Width="390" Height="22" Foreground="#E9EEF2" FontFamily="Consolas" FontSize="11.5"/>

        <TextBlock x:Name="LauncherStatus" Canvas.Left="380" Canvas.Top="315" Width="300" Height="18" Foreground="#82909B" FontFamily="Segoe UI" FontSize="8.5" TextAlignment="Right"/>
        <Canvas Canvas.Left="80" Canvas.Top="330" Width="600" Height="62">
          <Path Stroke="#313A43" StrokeThickness="1" StrokeStartLineCap="Square" StrokeEndLineCap="Square" StrokeLineJoin="Miter" Data="M 4,50 L 24,50 30,43 36,50 51,50 58,38 63,47 70,31 76,46 83,40 90,50 116,50 124,44 132,50 153,50 161,35 168,47 176,26 183,46 190,39 199,50 229,50 237,42 244,50 260,50 268,34 275,47 283,19 291,46 298,36 307,50 333,50 341,40 349,50 367,50 375,32 382,46 390,23 398,45 405,37 415,50 444,50 452,42 460,50 476,50 484,34 491,47 499,27 507,46 514,38 524,50 548,50 555,42 563,50 596,50"/>
          <Path x:Name="FlameEcho" Stroke="#9B3936" StrokeThickness="1" StrokeStartLineCap="Square" StrokeEndLineCap="Square" StrokeLineJoin="Miter" Data="M 4,55 L 29,55 35,51 41,55 66,55 73,49 80,55 103,55 111,50 119,55 146,55 153,48 161,55 188,55 196,51 204,55 232,55 240,49 248,55 275,55 283,50 291,55 319,55 327,48 335,55 362,55 370,51 378,55 406,55 414,49 422,55 449,55 457,50 465,55 493,55 501,48 509,55 536,55 544,51 552,55 596,55">
            <Path.Clip><RectangleGeometry x:Name="EchoClip" Rect="0,0,0,62"/></Path.Clip>
          </Path>
          <Path x:Name="FlameProgress" Stroke="#FF5A50" StrokeThickness="1.7" StrokeStartLineCap="Square" StrokeEndLineCap="Square" StrokeLineJoin="Miter" Data="M 4,50 L 24,50 30,43 36,50 51,50 58,38 63,47 70,31 76,46 83,40 90,50 116,50 124,44 132,50 153,50 161,35 168,47 176,26 183,46 190,39 199,50 229,50 237,42 244,50 260,50 268,34 275,47 283,19 291,46 298,36 307,50 333,50 341,40 349,50 367,50 375,32 382,46 390,23 398,45 405,37 415,50 444,50 452,42 460,50 476,50 484,34 491,47 499,27 507,46 514,38 524,50 548,50 555,42 563,50 596,50">
            <Path.Effect><DropShadowEffect BlurRadius="5" ShadowDepth="0" Opacity="0.55" Color="#FF5A50"/></Path.Effect>
            <Path.Clip><RectangleGeometry x:Name="ProgressClip" Rect="0,0,0,62"/></Path.Clip>
          </Path>
        </Canvas>

        <Canvas Canvas.Left="267" Canvas.Top="432" Width="34" Height="34">
          <Ellipse Width="34" Height="34" Stroke="#FFE08A" StrokeThickness="1" Opacity="0.88"/>
          <Path Canvas.Left="8" Canvas.Top="8" Width="18" Height="18" Stretch="Uniform" Stroke="#FFE08A" StrokeThickness="1" Data="M 10,1 L 10,5 M 10,15 L 10,19 M 1,10 L 5,10 M 15,10 L 19,10 M 3.6,3.6 L 6.4,6.4 M 13.6,13.6 L 16.4,16.4 M 16.4,3.6 L 13.6,6.4 M 6.4,13.6 L 3.6,16.4 M 14,10 A 4,4 0 1 1 6,10 A 4,4 0 1 1 14,10"/>
        </Canvas>
        <Canvas Canvas.Left="315" Canvas.Top="432" Width="34" Height="34">
          <Ellipse Width="34" Height="34" Stroke="#5BB6FF" StrokeThickness="1" Opacity="0.88"/>
          <Path Canvas.Left="8" Canvas.Top="8" Width="18" Height="18" Stretch="Uniform" Stroke="#5BB6FF" StrokeThickness="1" Data="M 10,2 C 8,6 4,8 4,12 A 6,6 0 0 0 16,12 C 16,8 12,6 10,2 M 4,15 C 7,13 10,17 16,15"/>
        </Canvas>
        <Canvas Canvas.Left="363" Canvas.Top="432" Width="34" Height="34">
          <Ellipse Width="34" Height="34" Stroke="#7D8994" StrokeThickness="1" Opacity="0.88"/>
          <Path Canvas.Left="8" Canvas.Top="8" Width="18" Height="18" Stretch="Uniform" Stroke="#7D8994" StrokeThickness="1" Data="M 15,8 A 5,5 0 1 1 5,8 A 5,5 0 1 1 15,8 M 6,12 L 6,16 M 8.7,13 L 8.7,17 M 11.3,13 L 11.3,17 M 14,12 L 14,16 M 4,17 L 16,17"/>
        </Canvas>
        <Canvas Canvas.Left="411" Canvas.Top="432" Width="34" Height="34">
          <Ellipse Width="34" Height="34" Stroke="#FF5A50" StrokeThickness="1" Opacity="0.88"/>
          <Path Canvas.Left="8" Canvas.Top="8" Width="18" Height="18" Stretch="Uniform" Stroke="#FF5A50" StrokeThickness="1" Data="M 10,2 C 11,6 7,7 9,11 C 9,8 12,8 12,5 C 15,8 17,12 15,15 C 13,19 6,19 4,15 C 2,11 6,8 7,6 C 7,9 8,10 10,11"/>
        </Canvas>
        <Canvas Canvas.Left="459" Canvas.Top="432" Width="34" Height="34">
          <Ellipse Width="34" Height="34" Stroke="#54D181" StrokeThickness="1" Opacity="0.88"/>
          <Path Canvas.Left="8" Canvas.Top="8" Width="18" Height="18" Stretch="Uniform" Stroke="#54D181" StrokeThickness="1" Data="M 10,18 L 10,5 M 10,8 L 6,4 M 10,11 L 15,6 M 10,14 L 5,10 M 10,16 L 14,13 M 3,6 L 6,2 L 9,5 M 14,3 L 17,6 L 15,10 M 3,10 L 5,14 L 10,15"/>
        </Canvas>

        <TextBlock x:Name="LauncherVersion" Canvas.Left="635" Canvas.Top="477" Width="100" Foreground="#68737D" FontFamily="Segoe UI" FontSize="8.5" TextAlignment="Right"/>
      </Canvas>
    </Viewbox>
  </Border>
</Window>
'@
        $reader = New-Object System.Xml.XmlNodeReader ([xml]$xaml)
        $window = [Windows.Markup.XamlReader]::Load($reader)
        $workingWidth = [System.Windows.SystemParameters]::WorkArea.Width
        $desiredWidth = [Math]::Min(760, [Math]::Max(620, [Math]::Round($workingWidth * 0.40)))
        $window.Width = $desiredWidth
        $window.Height = [Math]::Round($desiredWidth * 500 / 760)
        $script:LauncherWindow = $window
        $script:LauncherFeed1 = $window.FindName("FeedLine1")
        $script:LauncherFeed2 = $window.FindName("FeedLine2")
        $script:LauncherFeed3 = $window.FindName("FeedLine3")
        $script:LauncherStatus = $window.FindName("LauncherStatus")
        $script:LauncherVersion = $window.FindName("LauncherVersion")
        $script:LauncherProgressClip = $window.FindName("ProgressClip")
        $script:LauncherEchoClip = $window.FindName("EchoClip")
        $script:LauncherVersion.Text = "WLX $Version"
        $script:LauncherLogPath = Join-Path $InstallRoot "launcher.log"
        $iconPath = Join-Path $InstallRoot $ShortcutIconName
        if (Test-Path -LiteralPath $iconPath -PathType Leaf) {
            try { $window.Icon = [System.Windows.Media.Imaging.BitmapFrame]::Create([Uri]$iconPath) } catch { }
        }
        $window.Add_MouseLeftButtonDown({ try { $script:LauncherWindow.DragMove() } catch { } })
        [void]$window.Show()
        Add-LauncherActivity "Reading launcher settings"
        Set-LauncherStatus "Starting launcher"
        Set-LauncherProgress 5
    } catch {
        $script:LauncherWindow = $null
        Write-Host "[WLX] The polished launcher could not open; continuing in console mode: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

function Close-LauncherWindow([int]$HoldMilliseconds = 0) {
    if ($null -eq $script:LauncherWindow) { return }
    if ($HoldMilliseconds -gt 0) {
        $remaining = $HoldMilliseconds
        while ($remaining -gt 0) {
            $slice = [Math]::Min(50, $remaining)
            Start-Sleep -Milliseconds $slice
            Invoke-LauncherPump
            $remaining -= $slice
        }
    }
    try { $script:LauncherWindow.Close() } catch { }
    $script:LauncherWindow = $null
}

function Complete-LauncherWindow([string]$Message, [string]$Status = "Collection ready") {
    if ($null -eq $script:LauncherWindow) { return }
    Add-LauncherActivity $Message
    Set-LauncherStatus $Status
    Set-LauncherProgress 100
    Close-LauncherWindow 1500
}

function Show-LauncherFailure([string]$Message) {
    if ($null -eq $script:LauncherWindow) { return }
    $shortMessage = $Message
    if ($shortMessage.Length -gt 105) { $shortMessage = $shortMessage.Substring(0, 102) + "..." }
    Add-LauncherActivity ("Update failed - " + $shortMessage)
    Set-LauncherStatus "Update needs attention - see launcher.log"
    Close-LauncherWindow 6000
}

function Write-Step(
    [string]$Message,
    [string]$LauncherMessage = "",
    [int]$LauncherProgress = -1,
    [string]$LauncherStatusText = ""
) {
    Write-Host "[WLX] $Message" -ForegroundColor Cyan
    if ($script:LauncherLogPath) {
        try { Add-Content -LiteralPath $script:LauncherLogPath -Encoding UTF8 -Value ("{0:o} [WLX] {1}" -f (Get-Date), $Message) } catch { }
    }
    if ($LauncherMessage) { Add-LauncherActivity $LauncherMessage }
    if ($LauncherStatusText) { Set-LauncherStatus $LauncherStatusText }
    if ($LauncherProgress -ge 0) { Set-LauncherProgress $LauncherProgress }
}

trap {
    $failure = $_.Exception.Message
    Write-Host "[WLX] Update failed: $failure" -ForegroundColor Red
    if ($script:LauncherLogPath) {
        try { Add-Content -LiteralPath $script:LauncherLogPath -Encoding UTF8 -Value ("{0:o} [WLX] FAILURE: {1}" -f (Get-Date), $failure) } catch { }
    }
    Show-LauncherFailure $failure
    exit 1
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

function ConvertTo-CockatriceCandidate([string]$Value) {
    if (-not $Value) { return "" }
    $candidate = [Environment]::ExpandEnvironmentVariables($Value).Trim()
    if ($candidate -match '^"([^"]+)"') {
        $candidate = $Matches[1]
    } elseif ($candidate -match '^(.+?\.exe)\s*,\s*-?\d+\s*$') {
        $candidate = $Matches[1]
    }
    $candidate = $candidate.Trim('"')
    if (Test-Path -LiteralPath $candidate -PathType Container -ErrorAction SilentlyContinue) {
        $candidate = Join-Path $candidate "Cockatrice.exe"
    }
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals([IO.Path]::GetFileName($candidate), "Cockatrice.exe")) {
        return ""
    }
    return $candidate
}

function Add-CockatriceCandidate($Candidates, $Seen, [string]$Value) {
    $candidate = ConvertTo-CockatriceCandidate $Value
    if ($candidate -and $Seen.Add($candidate)) {
        [void]$Candidates.Add($candidate)
    }
}

function Find-CockatriceExe([string]$Explicit, $Settings) {
    $candidates = New-Object System.Collections.Generic.List[string]
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    Add-CockatriceCandidate $candidates $seen $Explicit
    if ($Settings -and $Settings.PSObject.Properties.Name -contains "cockatrice_exe" -and $Settings.cockatrice_exe) {
        Add-CockatriceCandidate $candidates $seen ([string]$Settings.cockatrice_exe)
    }

    # A running copy reveals its real executable path even on a secondary drive.
    foreach ($process in @(Get-Process -Name "Cockatrice" -ErrorAction SilentlyContinue)) {
        try { Add-CockatriceCandidate $candidates $seen ([string]$process.Path) } catch { }
    }

    # Installed copies normally register either an App Paths entry or an
    # uninstall record. Those records retain custom D:, E:, and other paths.
    $appPathKeys = @(
        "Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\App Paths\Cockatrice.exe",
        "Registry::HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\App Paths\Cockatrice.exe",
        "Registry::HKEY_LOCAL_MACHINE\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\Cockatrice.exe"
    )
    foreach ($keyPath in $appPathKeys) {
        try {
            if (-not (Test-Path -LiteralPath $keyPath -ErrorAction SilentlyContinue)) { continue }
            $key = Get-Item -LiteralPath $keyPath -ErrorAction Stop
            Add-CockatriceCandidate $candidates $seen ([string]$key.GetValue(""))
            Add-CockatriceCandidate $candidates $seen ([string]$key.GetValue("Path"))
        } catch { }
    }

    $uninstallRoots = @(
        "Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "Registry::HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "Registry::HKEY_LOCAL_MACHINE\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($root in $uninstallRoots) {
        try {
            if (-not (Test-Path -LiteralPath $root -ErrorAction SilentlyContinue)) { continue }
            foreach ($entry in @(Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
                $record = Get-ItemProperty -LiteralPath $entry.PSPath -ErrorAction SilentlyContinue
                if ($null -eq $record) { continue }
                $recordFields = @($record.PSObject.Properties.Name)
                if ($recordFields -notcontains "DisplayName" -or [string]$record.DisplayName -notlike "*Cockatrice*") { continue }
                if ($recordFields -contains "DisplayIcon") {
                    Add-CockatriceCandidate $candidates $seen ([string]$record.DisplayIcon)
                }
                if ($recordFields -contains "InstallLocation" -and $record.InstallLocation) {
                    Add-CockatriceCandidate $candidates $seen (Join-Path ([string]$record.InstallLocation) "Cockatrice.exe")
                }
            }
        } catch { }
    }

    if ($env:ProgramFiles) { Add-CockatriceCandidate $candidates $seen (Join-Path $env:ProgramFiles "Cockatrice\Cockatrice.exe") }
    if (${env:ProgramFiles(x86)}) { Add-CockatriceCandidate $candidates $seen (Join-Path ${env:ProgramFiles(x86)} "Cockatrice\Cockatrice.exe") }
    if ($env:LOCALAPPDATA) {
        Add-CockatriceCandidate $candidates $seen (Join-Path $env:LOCALAPPDATA "Programs\Cockatrice\Cockatrice.exe")
        Add-CockatriceCandidate $candidates $seen (Join-Path $env:LOCALAPPDATA "Cockatrice\Cockatrice.exe")
    }
    if ($env:USERPROFILE) {
        Add-CockatriceCandidate $candidates $seen (Join-Path $env:USERPROFILE "scoop\apps\cockatrice\current\Cockatrice.exe")
    }
    try {
        $fromPath = Get-Command "Cockatrice.exe" -CommandType Application -ErrorAction Stop
        Add-CockatriceCandidate $candidates $seen ([string]$fromPath.Source)
    } catch { }

    # Existing Windows shortcuts are a fast, drive-agnostic source of truth.
    if ($env:OS -eq "Windows_NT") {
        try {
            $shell = New-Object -ComObject WScript.Shell
            $shortcutFolders = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
            foreach ($folderName in @("Desktop", "CommonDesktopDirectory", "StartMenu", "CommonStartMenu", "Programs", "CommonPrograms")) {
                try {
                    $specialFolder = [System.Enum]::Parse([Environment+SpecialFolder], $folderName)
                    $folder = [Environment]::GetFolderPath($specialFolder)
                    if ($folder) { [void]$shortcutFolders.Add($folder) }
                } catch { }
            }
            foreach ($folder in $shortcutFolders) {
                foreach ($link in @(Get-ChildItem -LiteralPath $folder -Filter "*.lnk" -File -Recurse -ErrorAction SilentlyContinue)) {
                    try {
                        $target = $shell.CreateShortcut($link.FullName).TargetPath
                        Add-CockatriceCandidate $candidates $seen ([string]$target)
                    } catch { }
                }
            }
        } catch { }
    }

    # Check conventional portable-game locations on every mounted filesystem
    # drive without recursively crawling entire disks.
    $driveRelativePaths = @(
        "Cockatrice\Cockatrice.exe",
        "Games\Cockatrice\Cockatrice.exe",
        "Apps\Cockatrice\Cockatrice.exe",
        "Applications\Cockatrice\Cockatrice.exe",
        "Program Files\Cockatrice\Cockatrice.exe",
        "Program Files (x86)\Cockatrice\Cockatrice.exe"
    )
    foreach ($drive in @(Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
        if (-not $drive.Root) { continue }
        foreach ($relativePath in $driveRelativePaths) {
            Add-CockatriceCandidate $candidates $seen (Join-Path $drive.Root $relativePath)
        }
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

function Select-CockatriceExe([string]$SuggestedPath, [string]$DialogTitle) {
    if ($env:OS -ne "Windows_NT") { return "" }
    $dialog = $null
    try {
        $useWpfDialog = $null -ne $script:LauncherWindow
        if ($useWpfDialog) {
            Add-Type -AssemblyName PresentationFramework
            $dialog = New-Object Microsoft.Win32.OpenFileDialog
        } else {
            Add-Type -AssemblyName System.Windows.Forms
            $dialog = New-Object System.Windows.Forms.OpenFileDialog
        }
        $dialog.Title = $DialogTitle
        $dialog.Filter = "Cockatrice (Cockatrice.exe)|Cockatrice.exe|Windows applications (*.exe)|*.exe"
        $dialog.FileName = "Cockatrice.exe"
        $dialog.CheckFileExists = $true
        $dialog.Multiselect = $false
        $dialog.RestoreDirectory = $true
        $candidate = ConvertTo-CockatriceCandidate $SuggestedPath
        if ($candidate) {
            $suggestedDirectory = Split-Path -Parent $candidate
            if (Test-Path -LiteralPath $suggestedDirectory -PathType Container) {
                $dialog.InitialDirectory = $suggestedDirectory
            }
        }
        if ($useWpfDialog) {
            if ($dialog.ShowDialog($script:LauncherWindow) -ne $true) { return "" }
        } elseif ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            return ""
        }
        $selected = ConvertTo-CockatriceCandidate $dialog.FileName
        if ($selected -and (Test-Path -LiteralPath $selected -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $selected).Path
        }
        Write-Host "[WLX] The selected file was not Cockatrice.exe." -ForegroundColor Yellow
    } catch {
        Write-Host "[WLX] The Cockatrice file picker could not be opened: $($_.Exception.Message)" -ForegroundColor Yellow
    } finally {
        if ($null -ne $dialog -and $dialog -is [IDisposable]) { $dialog.Dispose() }
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
    $bootstrapPath = Join-Path $InstallRoot "WLX_Bootstrap.ps1"
    $powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $powershellPath -PathType Leaf)) {
        $powershellPath = [string](Get-Command "powershell.exe" -CommandType Application -ErrorAction Stop).Source
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $powershellPath
    $shortcut.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File `"$bootstrapPath`""
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

Initialize-LauncherWindow ([string]$config.version) $installRoot

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
Write-Step "Checking the hosted manifest..." "Checking the latest WLX release" 18 "Checking collection"
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
Write-Step "Found WLX version $($manifest.version)." "Found WLX $($manifest.version)" 30 "Release found"
if ($null -ne $script:LauncherWindow) { $script:LauncherVersion.Text = "WLX $($manifest.version)" }
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
    Write-Step "Downloading and verifying the custom-set XML..." "Downloading card database" 43 "Updating collection"
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

    Write-Step "Checking for numbered or duplicate ghost XML files..." "Checking duplicate collection files" 58 "Verifying update"
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
        Write-Step "Canonical XML is already current (version $($manifest.version))." "Collection is already current" 74 "Collection current"
    } else {
        Move-Item -LiteralPath $stagingPath -Destination $destination -Force
        Write-Step "Installed one canonical XML: $destination" "Installed the current card database" 74 "Installing update"
    }

    $cacheIdentities = @($currentIdentities) + @($legacyIdentities) + @($duplicateIdentities)
    if ($quarantinedXml.Count -gt 0) {
        $quarantinedPictures += @(Repair-FilesystemPictureCache $picsDir $cacheIdentities $installRoot $quarantineStamp)
    }
    if ($changedPictureIdentities.Count -gt 0) {
        Write-Step "Printing or artwork changes detected; refreshing only the matching Cockatrice picture cache entries..." "Refreshing the artwork cache" 86 "Finishing up"
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

$savedExe = ""
if ($settings -and $settings.PSObject.Properties.Name -contains "cockatrice_exe" -and $settings.cockatrice_exe) {
    $savedExe = [string]$settings.cockatrice_exe
}
Write-Step "Checking the remembered Cockatrice executable location..." "Checking saved Cockatrice location" 91 "Preparing Cockatrice"
$resolvedExe = ""
$explicitExe = ConvertTo-CockatriceCandidate $CockatriceExe
if ($explicitExe -and (Test-Path -LiteralPath $explicitExe -PathType Leaf)) {
    $resolvedExe = (Resolve-Path -LiteralPath $explicitExe).Path
} else {
    $savedCandidate = ConvertTo-CockatriceCandidate $savedExe
    if ($savedCandidate -and (Test-Path -LiteralPath $savedCandidate -PathType Leaf)) {
        $resolvedExe = (Resolve-Path -LiteralPath $savedCandidate).Path
    }
}
if (-not $resolvedExe) {
    $suggestedExe = Find-CockatriceExe $CockatriceExe $settings
    if ($NoLaunch) {
        # Automated tests may resolve a harmless executable without opening a GUI.
        $resolvedExe = $suggestedExe
    } else {
        if ($savedExe) {
            Write-Host "[WLX] Hey idiot, where did you move your files? Choose Cockatrice.exe again." -ForegroundColor Yellow
            Add-LauncherActivity "Hey idiot, where did you move your files?"
            Set-LauncherStatus "Choose Cockatrice.exe again"
            $dialogTitle = "Hey idiot, where did you move your Cockatrice files?"
        } else {
            Write-Step "First-time setup: choose Cockatrice.exe once. WLX will remember this exact location." "Choose Cockatrice.exe once" 92 "One-time setup"
            $dialogTitle = "Choose Cockatrice.exe (one-time setup)"
        }
        $resolvedExe = Select-CockatriceExe $suggestedExe $dialogTitle
    }
}
$rememberedExe = $resolvedExe
if (-not $rememberedExe -and $savedExe) { $rememberedExe = $savedExe }
$newSettings = [ordered]@{
    manifest_url = $ManifestUrl
    cockatrice_data_dir = $CockatriceDataDir
    cockatrice_pics_dir = $picsDir
    cockatrice_network_cache_dir = $networkCacheDir
    cockatrice_exe = $rememberedExe
}
$newSettings | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $settingsPath -Encoding UTF8
if ($resolvedExe) {
    Write-Step "Cockatrice executable location is ready." "Cockatrice location remembered" 94 "Ready to launch"
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
    Complete-LauncherWindow "Collection ready - Cockatrice is already open"
    exit 0
}
if ($resolvedExe) {
    Write-Step "Launching Cockatrice..." "Collection ready - opening Cockatrice" 100 "Collection ready"
    Start-Process -FilePath $resolvedExe
    Close-LauncherWindow 1500
} else {
    Write-Step "Update complete. Cockatrice was not launched because no executable was selected."
    Write-Host "Use the WLX shortcut again when you are ready to choose Cockatrice.exe." -ForegroundColor Yellow
    Complete-LauncherWindow "Update complete - choose Cockatrice.exe next time" "Update complete"
}
