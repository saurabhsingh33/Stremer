# Build MSI Installer for Stremer Windows Client
# Run this from client-windows directory

# Clean up any running processes
Write-Host "Checking for running Stremer processes..." -ForegroundColor Cyan
taskkill /F /IM Stremer.exe 2>$null | Out-Null
taskkill /F /IM python.exe 2>$null | Out-Null
Start-Sleep -Seconds 2

# Aggressively clean build directories
Write-Host "Removing old build directories..." -ForegroundColor Cyan
$dirs = @("build", "dist", "__pycache__")
foreach ($dir in $dirs) {
    if (Test-Path $dir) {
        Write-Host "  Removing $dir..."
        try {
            Remove-Item -Path $dir -Recurse -Force -ErrorAction Stop
            Start-Sleep -Milliseconds 200
        } catch {
            Write-Host "  WARNING: Could not remove $dir - trying with admin..." -ForegroundColor Yellow
        }
    }
}

Write-Host "Build directories cleaned." -ForegroundColor Green
Start-Sleep -Seconds 1

# Step 1: Build executable with PyInstaller (without --clean flag to avoid issues)
Write-Host "`nBuilding executable with PyInstaller..." -ForegroundColor Cyan
pyinstaller stremer.spec

if (-not (Test-Path "dist\Stremer\Stremer.exe")) {
    Write-Host "ERROR: PyInstaller build failed!" -ForegroundColor Red
    exit 1
}

Write-Host "Executable built successfully at dist\Stremer\Stremer.exe" -ForegroundColor Green

# Step 2: Generate WiX file list using Heat
Write-Host "`nGenerating WiX component list..." -ForegroundColor Cyan
& heat dir dist\Stremer `
    -cg ProductComponents `
    -dr DISTFOLDER `
    -gg `
    -sfrag `
    -srd `
    -out installer\Files.wxs

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Heat failed! Make sure WiX Toolset is installed." -ForegroundColor Red
    Write-Host "Download from: https://wixtoolset.org/releases/" -ForegroundColor Yellow
    exit 1
}

# Step 3: Compile WiX source files
Write-Host "`nCompiling WiX source files..." -ForegroundColor Cyan
& candle installer\Product.wxs installer\Files.wxs -o installer\obj\ -ext WixUIExtension

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Candle compilation failed!" -ForegroundColor Red
    exit 1
}

# Step 4: Link into MSI
Write-Host "`nLinking MSI installer..." -ForegroundColor Cyan
& light installer\obj\Product.wixobj installer\obj\Files.wixobj `
    -o installer\Stremer-Setup.msi `
    -ext WixUIExtension

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Light linking failed!" -ForegroundColor Red
    exit 1
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "SUCCESS! MSI installer created at:" -ForegroundColor Green
Write-Host "installer\Stremer-Setup.msi" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

# Optional: Sign the MSI (requires certificate)
# signtool sign /f YourCertificate.pfx /p YourPassword /t http://timestamp.digicert.com installer\Stremer-Setup.msi
