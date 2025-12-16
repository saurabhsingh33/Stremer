# Build NSIS Installer (Alternative to WiX)
# Simpler, no dependencies beyond NSIS itself

Write-Host "Building NSIS installer..." -ForegroundColor Cyan

# Ensure dist exists; if not, build with PyInstaller
if (-not (Test-Path "dist\Stremer\Stremer.exe")) {
    Write-Host "dist\\Stremer not found. Building executable with PyInstaller..." -ForegroundColor Yellow
    pyinstaller stremer.spec --noconfirm
    if (-not (Test-Path "dist\Stremer\Stremer.exe")) {
        Write-Host "ERROR: PyInstaller build failed; dist\\Stremer\\Stremer.exe not found." -ForegroundColor Red
        exit 1
    }
}

# Check if NSIS is installed (deterministic detection)
$nsis_path = $null

# Prefer Program Files locations
$pf64 = "$Env:ProgramFiles\NSIS\makensis.exe"
$pf86 = "$Env:ProgramFiles(x86)\NSIS\makensis.exe"
if (Test-Path $pf64) { $nsis_path = $pf64 }
elseif (Test-Path $pf86) { $nsis_path = $pf86 }

# Fallback to PATH
if (-not $nsis_path) {
    $nsis_cmd = Get-Command makensis -ErrorAction SilentlyContinue
    if ($nsis_cmd) { $nsis_path = $nsis_cmd.Source }
}

if (-not $nsis_path) {
    Write-Host "ERROR: NSIS (makensis) not found in PATH or common install locations." -ForegroundColor Red
    Write-Host "Download: https://nsis.sourceforge.io/" -ForegroundColor Yellow
    Write-Host "If already installed, reopen PowerShell or add makensis to PATH." -ForegroundColor Yellow
    Write-Host "Example to run directly if installed: '""C:\Program Files (x86)\NSIS\makensis.exe"" installer\Stremer-Setup.nsi'" -ForegroundColor Yellow
    exit 1
}

# Ensure we handle spaces in path
$nsis_path = $nsis_path.Trim()
Write-Host "Found NSIS at: $nsis_path" -ForegroundColor Green

# Build the installer
if (-not (Test-Path "installer\Stremer-Setup.nsi")) {
    Write-Host "ERROR: installer\\Stremer-Setup.nsi not found." -ForegroundColor Red
    exit 1
}

Write-Host "Packaging with NSIS..." -ForegroundColor Cyan
& "$nsis_path" "installer\Stremer-Setup.nsi"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "SUCCESS! NSIS installer created at:" -ForegroundColor Green
    Write-Host "installer\Stremer-Setup.exe" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host "`nERROR: NSIS build failed!" -ForegroundColor Red
    exit 1
}
