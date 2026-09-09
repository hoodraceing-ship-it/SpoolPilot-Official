#requires -Version 5.1

[CmdletBinding()]
param(
    [string]$Port = 'COM9',
    [string]$Pm3Path = 'C:\Users\hoodr\Downloads\rrg_other-20260802-da509461b734a61994f8e430e3151e9084bf9718\client\proxmark3.exe',
    [string]$DumpPath = 'C:\BambuRFID\hf-mf-064729CE-dump.bin',
    [string]$KeyPath = 'C:\BambuRFID\hf-mf-064729CE-key.bin',
    [ValidateRange(2, 20)]
    [int]$Retries = 8
)

$ErrorActionPreference = 'Stop'
$DefaultKey = 'FFFFFFFFFFFF'
$FactoryUid = 'AA55C396'
$LogPath = Join-Path (Split-Path -Parent $DumpPath) 'Write-BambuFuidStaged.log'

function Write-Status {
    param([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::Gray)
    Write-Host $Message -ForegroundColor $Color
    Add-Content -LiteralPath $LogPath -Value ("{0:u} {1}" -f (Get-Date), $Message)
}

function ConvertTo-Hex {
    param([byte[]]$Bytes)
    return -join ($Bytes | ForEach-Object { $_.ToString('X2') })
}

function Get-BlockBytes {
    param([byte[]]$Bytes, [int]$Block)
    $start = $Block * 16
    return [byte[]]$Bytes[$start..($start + 15)]
}

function Get-KeyA {
    param([int]$Sector)
    $start = $Sector * 6
    return ConvertTo-Hex ([byte[]]$script:KeyBytes[$start..($start + 5)])
}

function Get-KeyB {
    param([int]$Sector)
    $start = 96 + ($Sector * 6)
    return ConvertTo-Hex ([byte[]]$script:KeyBytes[$start..($start + 5)])
}

function Remove-Ansi {
    param([string]$Text)
    $ansi = [string][char]27 + '\[[0-?]*[ -/]*[@-~]'
    return [regex]::Replace($Text, $ansi, '')
}

function Invoke-Pm3 {
    param([Parameter(Mandatory)][string]$Command)
    $oldLocation = Get-Location
    try {
        $clientDirectory = Split-Path -Parent $Pm3Path
        $sessionLogDirectory = Join-Path $clientDirectory '.proxmark3\logs'
        $commandStarted = Get-Date
        Set-Location -LiteralPath $clientDirectory
        # The RRG Windows bundle requires setup.bat plus its Bash `pm3`
        # wrapper. Calling proxmark3.exe directly produces no usable output.
        $escapedCommand = $Command.Replace('"', '\"')
        $launcherCommand = 'call setup.bat && bash pm3 -f -p {0} -c "{1}"' -f $Port, $escapedCommand
        # Proxmark reports recoverable RF/PRNG diagnostics on stderr. Capture
        # them for command evaluation without letting PowerShell convert them
        # into terminating NativeCommandError exceptions.
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $lines = & $env:ComSpec /d /s /c $launcherCommand 2>&1
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
        $text = Remove-Ansi (($lines | Out-String))

        # Some Windows builds write through the console API instead of the
        # redirected stdout pipe. Their per-session log remains complete.
        if (Test-Path -LiteralPath $sessionLogDirectory -PathType Container) {
            Start-Sleep -Milliseconds 100
            $sessionLog = Get-ChildItem -LiteralPath $sessionLogDirectory -File -Filter 'log_*.txt' |
                Where-Object { $_.LastWriteTime -ge $commandStarted.AddSeconds(-2) } |
                Sort-Object LastWriteTime -Descending |
                Select-Object -First 1
            if ($null -ne $sessionLog) {
                $sessionText = Remove-Ansi (Get-Content -LiteralPath $sessionLog.FullName -Raw)
                if (-not [string]::IsNullOrWhiteSpace($sessionText)) {
                    $text = $sessionText
                }
            }
        }

        $script:LastPm3Output = $text
        Add-Content -LiteralPath $LogPath -Value ("COMMAND: {0}`r`n{1}" -f $Command, $text)
        if ($text -match 'invalid serial port|access.+denied|could not open') {
            Start-Sleep -Milliseconds 2500
        }
        else {
            Start-Sleep -Milliseconds 900
        }
        return $text
    }
    finally {
        Set-Location -LiteralPath $oldLocation
    }
}

function Read-BlockOnce {
    param(
        [int]$Block,
        [string]$Key,
        [ValidateSet('A', 'B')][string]$KeyType = 'A'
    )
    $typeOption = if ($KeyType -eq 'B') { ' -b' } else { '' }
    $output = Invoke-Pm3 ("hf mf rdbl --blk {0}{1} -k {2}" -f $Block, $typeOption, $Key)
    $pattern = '(?m)^\[[^\]]+\]\s*' + [regex]::Escape([string]$Block) + '\s+\|\s*((?:[0-9A-Fa-f]{2}\s+){15}[0-9A-Fa-f]{2})\s+\|'
    $match = [regex]::Match($output, $pattern)
    if (-not $match.Success) {
        return $null
    }
    return ($match.Groups[1].Value -replace '\s', '').ToUpperInvariant()
}

function Read-BlockWithAuth {
    param([int]$Block)
    $sector = [math]::Floor($Block / 4)
    $candidates = @(
        [pscustomobject]@{ Name = 'default-A'; Key = $DefaultKey; Type = 'A'; Sealed = $false },
        [pscustomobject]@{ Name = 'default-B'; Key = $DefaultKey; Type = 'B'; Sealed = $false },
        [pscustomobject]@{ Name = 'target-A';  Key = (Get-KeyA $sector); Type = 'A'; Sealed = $true },
        [pscustomobject]@{ Name = 'target-B';  Key = (Get-KeyB $sector); Type = 'B'; Sealed = $true }
    )

    $seen = @{}
    foreach ($candidate in $candidates) {
        $identity = $candidate.Type + ':' + $candidate.Key
        if ($seen.ContainsKey($identity)) { continue }
        $seen[$identity] = $true
        $value = Read-BlockOnce -Block $Block -Key $candidate.Key -KeyType $candidate.Type
        if ($null -ne $value) {
            return [pscustomobject]@{
                Data = $value
                Auth = $candidate
            }
        }
    }
    return $null
}

function Write-BlockOnce {
    param(
        [int]$Block,
        [string]$Data,
        [string]$Key,
        [ValidateSet('A', 'B')][string]$KeyType = 'A'
    )
    $typeOption = if ($KeyType -eq 'B') { ' -b' } else { '' }
    $output = Invoke-Pm3 ("hf mf wrbl --blk {0}{1} -k {2} -d {3}" -f $Block, $typeOption, $Key, $Data)
    return ($output -match 'Write\s*\(\s*ok\s*\)')
}

function Set-DataBlock {
    param([int]$Block, [string]$Target)

    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        $current = Read-BlockWithAuth -Block $Block
        if ($null -ne $current -and $current.Data -eq $Target) {
            Write-Status ("Block {0,2}: verified" -f $Block) Green
            return
        }

        if ($null -ne $current -and $current.Auth.Sealed) {
            throw "Block $Block differs from the dump, but its sector is already protected. This tag cannot be safely completed."
        }

        $writeKey = if ($null -ne $current) { $current.Auth.Key } else { $DefaultKey }
        $writeType = if ($null -ne $current) { $current.Auth.Type } else { 'A' }
        [void](Write-BlockOnce -Block $Block -Data $Target -Key $writeKey -KeyType $writeType)
        Start-Sleep -Milliseconds 200
    }
    throw "Block $Block could not be written and verified after $Retries attempts. Nothing irreversible was done by this failure."
}

function Get-Uid {
    $infoAttempts = [math]::Min(3, $Retries)
    for ($attempt = 1; $attempt -le $infoAttempts; $attempt++) {
        $output = Invoke-Pm3 'hf 14a info'
        $match = [regex]::Match($output, 'UID:\s*((?:[0-9A-Fa-f]{2}\s+){3}[0-9A-Fa-f]{2})')
        if ($match.Success) {
            return ($match.Groups[1].Value -replace '\s', '').ToUpperInvariant()
        }
        Start-Sleep -Milliseconds 200
    }

    # Some low-cost CUID/FUID tags return unreliable anticollision/BCC replies to
    # the extended info probe but still support authenticated Classic reads.
    # Recover the UID from bytes 0-3 of manufacturer block 0 as a fallback.
    $fallbackKeys = @(
        [pscustomobject]@{ Key = $DefaultKey; Type = 'A' },
        [pscustomobject]@{ Key = $DefaultKey; Type = 'B' },
        [pscustomobject]@{ Key = (Get-KeyA 0); Type = 'A' },
        [pscustomobject]@{ Key = (Get-KeyB 0); Type = 'B' }
    )
    foreach ($candidate in $fallbackKeys) {
        for ($attempt = 1; $attempt -le $Retries; $attempt++) {
            $blockZero = Read-BlockOnce -Block 0 -Key $candidate.Key -KeyType $candidate.Type
            if ($null -ne $blockZero -and $blockZero.Length -eq 32) {
                $uid = $blockZero.Substring(0, 8)
                Write-Status "UID recovered from manufacturer block 0: $uid" Yellow
                return $uid
            }
            Start-Sleep -Milliseconds 200
        }
    }

    Write-Host ''
    Write-Host 'Last Proxmark response:' -ForegroundColor Yellow
    Write-Host $script:LastPm3Output
    throw "The Proxmark could not read the UID through either anticollision or block 0. Check that no other Proxmark window owns $Port and see $LogPath."
}

function Test-SectorProtected {
    param([int]$Sector)
    $testBlock = $Sector * 4
    if ($Sector -eq 0) { $testBlock = 1 }
    $target = ConvertTo-Hex (Get-BlockBytes $script:DumpBytes $testBlock)
    foreach ($keyType in @('A', 'B')) {
        $key = if ($keyType -eq 'A') { Get-KeyA $Sector } else { Get-KeyB $Sector }
        for ($try = 1; $try -le 2; $try++) {
            $actual = Read-BlockOnce -Block $testBlock -Key $key -KeyType $keyType
            if ($actual -eq $target) { return $true }
        }
    }
    return $false
}

function Set-SectorTrailer {
    param([int]$Sector)
    $trailerBlock = ($Sector * 4) + 3
    $dumpTrailer = Get-BlockBytes $script:DumpBytes $trailerBlock
    $acl = ConvertTo-Hex ([byte[]]$dumpTrailer[6..9])
    $trailer = (Get-KeyA $Sector) + $acl + (Get-KeyB $Sector)

    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        if (Test-SectorProtected -Sector $Sector) {
            Write-Status ("Sector {0,2}: protected and verified" -f $Sector) Green
            return
        }
        [void](Write-BlockOnce -Block $trailerBlock -Data $trailer -Key $DefaultKey -KeyType 'A')
        Start-Sleep -Milliseconds 250
    }
    throw "Sector $Sector trailer could not be confirmed. Stop using this tag; do not place it in the AMS."
}

function Set-ManufacturerBlock {
    param([string]$TargetUid)
    $target = ConvertTo-Hex (Get-BlockBytes $script:DumpBytes 0)

    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        $uid = Get-Uid
        $readResult = Read-BlockWithAuth -Block 0
        $actual = if ($null -ne $readResult) { $readResult.Data } else { $null }
        if ($uid -eq $TargetUid -and $actual -eq $target) {
            Write-Status "Manufacturer block: permanent UID verified as $TargetUid" Green
            return
        }
        if ($uid -eq $TargetUid -and $null -eq $actual) {
            Start-Sleep -Milliseconds 250
            continue
        }
        if ($uid -eq $TargetUid) {
            throw "The permanent UID is already $TargetUid, but manufacturer block 0 does not match the dump. Do not use this tag."
        }
        if ($uid -ne $FactoryUid) {
            throw "The tag UID is $uid, not the expected factory UID $FactoryUid or target UID $TargetUid. Refusing to write block 0."
        }
        [void](Write-BlockOnce -Block 0 -Data $target -Key $DefaultKey -KeyType 'A')
        Start-Sleep -Milliseconds 300
    }
    throw 'The permanent manufacturer block could not be verified. Do not place this tag in the AMS.'
}

if (-not (Test-Path -LiteralPath $Pm3Path -PathType Leaf)) { throw "proxmark3.exe was not found: $Pm3Path" }
if (-not (Test-Path -LiteralPath $DumpPath -PathType Leaf)) { throw "Dump file was not found: $DumpPath" }
if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) { throw "Key file was not found: $KeyPath" }

[byte[]]$script:DumpBytes = [System.IO.File]::ReadAllBytes($DumpPath)
[byte[]]$script:KeyBytes = [System.IO.File]::ReadAllBytes($KeyPath)
if ($DumpBytes.Length -ne 1024) { throw "The dump must be exactly 1024 bytes; found $($DumpBytes.Length)." }
if ($KeyBytes.Length -ne 192) { throw "The key file must be exactly 192 bytes; found $($KeyBytes.Length)." }

$targetUid = ConvertTo-Hex ([byte[]]$DumpBytes[0..3])
$calculatedBcc = $DumpBytes[0] -bxor $DumpBytes[1] -bxor $DumpBytes[2] -bxor $DumpBytes[3]
if ($DumpBytes[4] -ne $calculatedBcc) {
    throw ('The dump has an invalid UID checksum: stored {0:X2}, expected {1:X2}.' -f $DumpBytes[4], $calculatedBcc)
}

Set-Content -LiteralPath $LogPath -Value ("Staged Bambu FUID writer started {0:u}" -f (Get-Date))
Write-Status "Target UID: $targetUid" Cyan
Write-Status "Port: $Port" Cyan
Write-Host ''
Write-Host 'IMPORTANT:' -ForegroundColor Yellow
Write-Host '  - Close every other Proxmark3 window first.' -ForegroundColor Yellow
Write-Host '  - Put only ONE tag flat and centered on the HF antenna.' -ForegroundColor Yellow
Write-Host '  - Do not move or remove it until this script finishes.' -ForegroundColor Yellow
Write-Host '  - The tag must be your fresh AA55C396 CUID/FUID sticker.' -ForegroundColor Yellow
Write-Host ''
$ready = Read-Host 'Type READY to begin the reversible data-block stage'
if ($ready.Trim() -ine 'READY') { throw 'Cancelled before writing.' }

Write-Status "Waiting for Windows to release $Port..." Cyan
Start-Sleep -Seconds 3

$startingUid = Get-Uid
if ($startingUid -ne $FactoryUid -and $startingUid -ne $targetUid) {
    throw "Unexpected tag UID $startingUid. Expected $FactoryUid (fresh) or $targetUid (resume)."
}

Write-Status 'Stage 1/4: writing and verifying ordinary data blocks...' Cyan
$dataBlocks = 0..63 | Where-Object { $_ -ne 0 -and ($_ % 4) -ne 3 }
foreach ($block in $dataBlocks) {
    $target = ConvertTo-Hex (Get-BlockBytes $DumpBytes $block)
    Set-DataBlock -Block $block -Target $target
}

Write-Host ''
Write-Host 'All ordinary data blocks match the Bambu PETG Basic Black dump.' -ForegroundColor Green
Write-Host 'The next stage changes the sector keys/access conditions and permanently changes the UID.' -ForegroundColor Red
Write-Host 'After block 0 is written, this write-once FUID tag cannot be restored to a blank tag.' -ForegroundColor Red
$confirmation = Read-Host 'Type LOCK to commit this tag'
if ($confirmation.Trim() -ine 'LOCK') {
    Write-Status 'Stopped safely before protected trailers and permanent UID.' Yellow
    exit 0
}

Write-Status 'Stage 2/4: programming protected trailers for sectors 1-15...' Cyan
foreach ($sector in 1..15) {
    Set-SectorTrailer -Sector $sector
}

Write-Status 'Stage 3/4: programming the permanent manufacturer block...' Cyan
Set-ManufacturerBlock -TargetUid $targetUid

Write-Status 'Stage 4/4: programming the sector 0 trailer and running final verification...' Cyan
Set-SectorTrailer -Sector 0

foreach ($block in $dataBlocks) {
    $target = ConvertTo-Hex (Get-BlockBytes $DumpBytes $block)
    $verified = $false
    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        $actual = Read-BlockWithAuth -Block $block
        if ($null -ne $actual -and $actual.Data -eq $target) {
            $verified = $true
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not $verified) {
        throw "Final verification failed at block $block. Do not place this tag in the AMS."
    }
}

$finalUid = Get-Uid
if ($finalUid -ne $targetUid) { throw "Final UID verification failed: read $finalUid, expected $targetUid." }

Write-Host ''
Write-Status "SUCCESS: tag $targetUid is fully written and verified." Green
Write-Status "Log saved to $LogPath" Cyan
Write-Host 'You can now remove it and test it in the AMS.' -ForegroundColor Green
