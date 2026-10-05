<#
.SYNOPSIS
    Verify the kivyforge Android examples end-to-end on a Windows host.

.DESCRIPTION
    For each example: clean, lock --check (or lock), doctor, build --debug,
    then optionally run + smoke on an emulator. Mirrors the Windows verifier.

    Requires: JDK, Android SDK/NDK, and (for --Run) an AVD. The qr-maven
    example additionally needs the JDK on PATH at lock time (Maven channel).

.PARAMETER Run
    Also boot the AVD, run each app and check its log reaches Kivy's main
    loop, and run the contract smoke test.

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
        # clean takes no -p: it removes every platform's generated tree.
        & $kivyforge clean
        if ($LASTEXITCODE -ne 0) { throw "clean failed" }
        & $kivyforge lock -p android --check
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  lock out of date; re-locking" -ForegroundColor Yellow
            & $kivyforge lock -p android
        }
        # doctor is advisory (it reports, it is not a build gate), so its exit
        # status is shown, not enforced; build and run below are the gates.
        & $kivyforge doctor -p android
        & $kivyforge build -p android --debug --abi x86_64
        if ($LASTEXITCODE -ne 0) { throw "build failed" }

        if ($Run) {
            # --no-follow: return after one snapshot instead of streaming the log.
            # Its stdout is the app's own log, so the launch is checked by what
            # the app logged: a zero exit only proves the app got a process.
            $log = & $kivyforge run -p android --emulator --avd $Avd --abi x86_64 --no-follow
            if ($LASTEXITCODE -ne 0) { throw "run failed" }
            if (-not ($log | Select-String -SimpleMatch "Start application main loop")) {
                $log | Select-Object -Last 40 | Write-Host
                throw "run: the app never reached Kivy's main loop (last 40 log lines above)"
            }
            Write-Host "  app reached Kivy's main loop"
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
