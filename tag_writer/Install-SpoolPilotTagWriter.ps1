#requires -Version 5.1

$ErrorActionPreference = 'Stop'
$appDirectory = Join-Path $env:LOCALAPPDATA 'SpoolPilotTagWriter'
$appFile = Join-Path $appDirectory 'SpoolPilot-Tag-Writer.exe'
$hashFile = Join-Path $appDirectory 'SpoolPilot-Tag-Writer.exe.sha256'
$releaseBase = 'https://github.com/hoodraceing-ship-it/SpoolPilot-Official/releases/latest/download'

Write-Host 'Installing SpoolPilot Tag Writer...' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $appDirectory | Out-Null
Invoke-WebRequest -Uri "$releaseBase/SpoolPilot-Tag-Writer.exe" -OutFile $appFile
Invoke-WebRequest -Uri "$releaseBase/SpoolPilot-Tag-Writer.exe.sha256" -OutFile $hashFile

$expectedHash = ((Get-Content -LiteralPath $hashFile -Raw).Trim() -split '\s+')[0]
$actualHash = (Get-FileHash -LiteralPath $appFile -Algorithm SHA256).Hash
if ($actualHash -ine $expectedHash) {
    Remove-Item -LiteralPath $appFile -Force -ErrorAction SilentlyContinue
    throw 'The downloaded app failed SHA-256 verification and was removed.'
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'SpoolPilot Tag Writer.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $appFile
$shortcut.WorkingDirectory = $appDirectory
$shortcut.Description = 'Search and write verified Bambu-compatible filament RFID tags'
$shortcut.Save()

Write-Host ''
Write-Host 'Installed successfully.' -ForegroundColor Green
Write-Host "Verified SHA-256: $actualHash"
Write-Host "Desktop shortcut: $shortcutPath"
Start-Process -FilePath $shortcutPath
