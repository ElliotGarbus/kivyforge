#Requires -Version 5.1
<#
.SYNOPSIS
    verify-windows-examples.ps1 - the Windows sibling of verify-desktop-examples.sh.

.DESCRIPTION
    Walks each desktop example that carries a [tool.kivy.windows] overlay through
    the full lifecycle, one at a time, so you can visually verify every operation
    and its result on a Windows host.

    For each example it runs, in order:
      0. native   - .\build_native.sh (via bash/git-bash) when present, else a
                    warning that the Windows native binaries must be produced
                    out-of-band (see build_native.sh's Windows branch).
      1. doctor   - kivyforge doctor -p windows      (pre-flight; non-gating)
      2. clean    - kivyforge clean                  (remove build\ + dist\)
      3. lock     - kivyforge lock  -p windows --update (regenerate + verify)
      4. build    - kivyforge build -p windows       (assemble the onedir bundle)
      5. run      - kivyforge run   -p windows       (launch the dev build; GUI)
      6. package  - kivyforge package -p windows     (copy to dist\windows, sign
                                                      when configured)
      7. artifact - launch the packaged launcher .exe (GUI)

    The lock step regenerates pylock.windows.toml from live PyPI to exercise the
    resolver, verifies it still matches the committed lock (ignoring the volatile
    generated_at line), then RESTORES the committed lock so your git tree stays
    clean. A semantic difference is reported as "lock drift" (non-fatal).
    Examples with no committed lock (e.g. hello-native, whose lock is gitignored)
    keep the freshly generated one. Pass -KeepLock to leave regenerated locks.

.PARAMETER Examples
    One or more example names to run (default: dice-roller, notes, hello-native).
    desktop-viewer is macOS-only, so it is not in the Windows default set.

.PARAMETER NoPause
    Do not wait for Enter between examples.

.PARAMETER NoGui
    Skip the GUI launches (run + artifact).

.PARAMETER KeepLock
    Keep regenerated locks in place (do not restore the committed lock).

.EXAMPLE
    .\verify-windows-examples.ps1
    .\verify-windows-examples.ps1 dice-roller -NoPause
    .\verify-windows-examples.ps1 -NoGui
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Examples,
    [switch]$NoPause,
    [switch]$NoGui,
    [switch]$KeepLock
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExamplesDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ExamplesDir

# Prefer the repo virtualenv's kivyforge if present.
$venvActivate = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) { . $venvActivate }

if (-not (Get-Command kivyforge -ErrorAction SilentlyContinue)) {
    Write-Error "'kivyforge' not found on PATH (activate the kivyforge venv first)."
    exit 1
}

$env:KIVYFORGE_PLATFORM = "windows"
$Lock = "pylock.windows.toml"
# desktop-viewer is macOS-only (osascript panel, ⌘ shortcuts) — no Windows overlay.
$DefaultExamples = @("dice-roller", "notes", "hello-native")
if (-not $Examples -or $Examples.Count -eq 0) { $Examples = $DefaultExamples }

$Passed = @(); $Failed = @(); $Skipped = @(); $Drifted = @()

function Run-Step {
    param([string]$Label, [scriptblock]$Action)
    Write-Host ""
    Write-Host ">>> $Label"
    try {
        # Stream the command's output straight to the console (Out-Host) so it is
        # visible; only the boolean below flows out as this function's return, so
        # callers can do `$ok = Run-Step ...` without capturing command output.
        & $Action | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "$Label exited with $LASTEXITCODE" }
        return $true
    } catch {
        Write-Host "!!! $Label FAILED: $_"
        return $false
    }
}

function Lock-Body {
    param([string]$Path)
    # Strip the volatile generated_at line so lock comparison is semantic.
    Get-Content $Path | Where-Object { $_ -notmatch '^generated_at ' }
}

function Verify-Lock {
    $script:DriftThis = $false
    $backup = $null
    if (Test-Path $Lock) {
        $backup = [System.IO.Path]::GetTempFileName()
        Copy-Item $Lock $backup -Force
    }
    if (-not (Run-Step "lock" { kivyforge lock -p windows --update })) {
        if ($backup) { Remove-Item $backup -Force }
        return $false
    }
    if (-not $backup) {
        Write-Host "    no committed $Lock to compare; keeping the generated one."
        return $true
    }
    $before = Lock-Body $backup
    $after = Lock-Body $Lock
    if (Compare-Object $before $after) {
        Write-Host "!!! lock DRIFT: regenerated $Lock differs from the committed one."
        $script:DriftThis = $true
    } else {
        Write-Host "    lock matches the committed reference (ignoring generated_at)."
    }
    if ($KeepLock) {
        Write-Host "    keeping the regenerated lock (-KeepLock)."
    } else {
        Copy-Item $backup $Lock -Force
        Write-Host "    restored the committed lock (git tree left clean)."
    }
    Remove-Item $backup -Force
    return $true
}

function Launch-Artifact {
    param([string]$ExampleDir)
    $distRoot = Join-Path $ExampleDir "dist\windows"
    $folder = Get-ChildItem $distRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $folder) {
        Write-Host "!!! artifact: no packaged folder under dist\windows\"
        return $false
    }
    $exe = Get-ChildItem $folder.FullName -Filter *.exe |
        Where-Object { $_.Name -ne "python.exe" } | Select-Object -First 1
    if (-not $exe) {
        Write-Host "!!! artifact: no launcher .exe in $($folder.FullName)"
        return $false
    }
    Write-Host ""
    Write-Host ">>> artifact: launching $($exe.FullName)"
    # The launcher is a /SUBSYSTEM:WINDOWS (GUI) exe; PowerShell's call operator
    # does NOT wait for GUI apps, so -Wait is required or the script races ahead
    # and prompts for the next example before this window is even closed.
    Start-Process -FilePath $exe.FullName -Wait
    return $true
}

foreach ($ex in $Examples) {
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "  $ex  (windows)"
    Write-Host "============================================================"

    $dir = Join-Path $ExamplesDir "desktop\$ex"
    if (-not (Test-Path $dir)) {
        Write-Host "!!! ${ex}: directory not found under examples\desktop\"
        $Failed += $ex; continue
    }
    $pyproject = Join-Path $dir "pyproject.toml"
    if (-not (Select-String -Path $pyproject -Pattern '^\[tool\.kivy\.windows(\]|\.)' -Quiet)) {
        Write-Host ">>> ${ex}: no [tool.kivy.windows] overlay - skipping"
        $Skipped += $ex; continue
    }

    Push-Location $dir
    $ok = $true
    $script:DriftThis = $false
    try {
        # 0. native pre-step - hello-native builds two native binaries. Prefer
        #    the MSVC-based build_native.ps1 (typical Windows dev box has Visual
        #    Studio, not mingw); fall back to build_native.sh via bash when a
        #    real bash + gcc/clang is available; else warn.
        if (Test-Path ".\build_native.ps1") {
            if (-not (Run-Step "native" { & .\build_native.ps1 })) { $ok = $false }
        } elseif (Test-Path ".\build_native.sh") {
            $bash = Get-Command bash -ErrorAction SilentlyContinue
            if ($bash) {
                if (-not (Run-Step "native" { bash ./build_native.sh })) { $ok = $false }
            } else {
                Write-Host ">>> native: no build_native.ps1 and bash not found; " `
                    "assuming binaries\windows\ is already populated."
            }
        }
        if ($ok) {
            Run-Step "doctor" { kivyforge doctor -p windows } | Out-Null
        }
        if ($ok) { $ok = Run-Step "clean" { kivyforge clean } }
        if ($ok) { $ok = Verify-Lock }
        if ($script:DriftThis) { $Drifted += $ex }
        if ($ok) { $ok = Run-Step "build" { kivyforge build -p windows } }
        if ($ok -and -not $NoGui) {
            $ok = Run-Step "run" { kivyforge run -p windows }
        } elseif ($NoGui) {
            Write-Host ">>> run: skipped (-NoGui)"
        }
        if ($ok) { $ok = Run-Step "package" { kivyforge package -p windows } }
        if ($ok -and -not $NoGui) {
            $ok = Launch-Artifact -ExampleDir $dir
        } elseif ($NoGui) {
            Write-Host ">>> artifact: skipped (-NoGui)"
        }
    } finally {
        Pop-Location
    }

    if ($ok) {
        Write-Host "`n+++ ${ex}: OK"; $Passed += $ex
    } else {
        Write-Host "`n--- ${ex}: FAILED"; $Failed += $ex
    }

    if (-not $NoPause -and $ex -ne $Examples[-1]) {
        Read-Host "Verified '$ex'? Press Enter for the next example"
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host "  Summary (windows)"
Write-Host "============================================================"
Write-Host "passed ($($Passed.Count)): $($Passed -join ', ')"
Write-Host "failed ($($Failed.Count)): $($Failed -join ', ')"
if ($Skipped.Count -gt 0) {
    Write-Host "skipped ($($Skipped.Count)): $($Skipped -join ', ') (no [tool.kivy.windows] overlay)"
}
if ($Drifted.Count -gt 0) {
    Write-Host "lock drift ($($Drifted.Count)): $($Drifted -join ', ')"
    Write-Host "  ^ re-lock and recommit these when you're ready."
}

if ($Failed.Count -ne 0) { exit 1 }
