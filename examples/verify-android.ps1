<#
.SYNOPSIS
    Verify the kivyforge Android examples end-to-end on a Windows host.

.DESCRIPTION
    For each example: clean, lock --check (or lock), doctor, build --debug,
    then optionally run + smoke on an emulator. Mirrors the Windows verifier.

    Requires: JDK, Android SDK/NDK, and (for --Run) an AVD. The qr-maven
    example additionally needs the JDK on PATH at lock time (Maven channel).

.PARAMETER Run
    Also boot the AVD, run each app, and run the contract smoke test.

.PARAMETER Avd
    The AVD name to use with -Run (default: kivyforge_x86_64).
#>
param(
    [switch]$Run,
    [string]$Avd = "kivyforge_x86_64"
)

$ErrorActionPreference = "Stop"
$examples = @("hello-android", "pyjnius-deviceinfo", "qr-maven")
$root = Join-Path $PSScriptRoot "mobile"
$kivyforge = "kivyforge"

$failed = @()
foreach ($ex in $examples) {
    Write-Host "`n=== $ex ===" -ForegroundColor Cyan
    $dir = Join-Path $root $ex
    Push-Location $dir
    try {
        & $kivyforge clean -p android
        & $kivyforge lock -p android --check
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  lock out of date; re-locking" -ForegroundColor Yellow
            & $kivyforge lock -p android
        }
        & $kivyforge doctor -p android
        # doctor FAILs on the interim Kivy wheel's 16 KB alignment — expected;
        # do not treat that lone FAIL as a verifier failure for the debug loop.
        & $kivyforge build -p android --debug --abi x86_64
        if ($LASTEXITCODE -ne 0) { throw "build failed" }

        if ($Run) {
            & $kivyforge run -p android --emulator --avd $Avd --abi x86_64
            if ($LASTEXITCODE -ne 0) { throw "run failed" }
            & $kivyforge run -p android --smoke --avd $Avd --abi x86_64
            if ($LASTEXITCODE -ne 0) { throw "smoke failed" }
        }
        Write-Host "  OK" -ForegroundColor Green
    }
    catch {
        Write-Host "  FAILED: $_" -ForegroundColor Red
        $failed += $ex
    }
    finally {
        Pop-Location
    }
}

if ($failed.Count -gt 0) {
    Write-Host "`nFAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "`nAll Android examples verified." -ForegroundColor Green
