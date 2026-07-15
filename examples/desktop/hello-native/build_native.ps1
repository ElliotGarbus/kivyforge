#Requires -Version 5.1
<#
.SYNOPSIS
    build_native.ps1 - Windows sibling of build_native.sh, using MSVC.

.DESCRIPTION
    Compiles this example's two non-wheel native binaries into
    binaries\windows\{roll.exe,greet.dll} with the Visual Studio C++ toolset
    (cl), the same toolchain kivyforge uses to build its launcher. Use this on a
    Windows host that has Visual Studio / Build Tools but not mingw/git-bash
    (build_native.sh's Windows branch needs gcc/clang under bash).

    The toolset is located with vswhere and loaded via vcvars64.bat, so you do
    NOT need to run from a Developer Command Prompt. greet()'s
    __declspec(dllexport) (see native\libgreet.c) lands in the DLL export table,
    so ctypes.WinDLL("greet.dll").greet resolves at runtime.

    Output is gitignored (build artifacts). Run once before
    `kivyforge lock -p windows`.
.EXAMPLE
    .\build_native.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Src = Join-Path $Here "native"
$Out = Join-Path $Here "binaries\windows"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

# Locate the VC++ toolset with vswhere (same discovery as build_launcher.py).
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    Write-Error "vswhere not found at $vswhere; install Visual Studio (with the C++ build tools)."
    exit 2
}
$install = & $vswhere -latest -products * `
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath
if (-not $install) {
    Write-Error "no Visual Studio install with the C++ x64 toolset was found (vswhere returned nothing)."
    exit 2
}
$vcvars = Join-Path ($install | Select-Object -First 1) "VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path $vcvars)) {
    Write-Error "vcvars64.bat not found at $vcvars."
    exit 2
}

# Compile in a temp dir (cl scatters .obj/.lib/.exp beside the CWD), copy the
# two artifacts out. /LD builds greet.dll; /Fe names each output.
$tmp = Join-Path $env:TEMP ("hello-native-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
    $bat = Join-Path $tmp "build.bat"
    @"
@echo off
call "$vcvars" >nul || exit /b 1
cl /nologo /O2 /Fe:"$tmp\roll.exe" "$Src\roll.c" || exit /b 1
cl /nologo /O2 /LD /Fe:"$tmp\greet.dll" "$Src\libgreet.c" || exit /b 1
"@ | Set-Content -Path $bat -Encoding Ascii
    & cmd /c $bat
    if ($LASTEXITCODE -ne 0) { Write-Error "MSVC compile failed (exit $LASTEXITCODE)."; exit 1 }
    Copy-Item (Join-Path $tmp "roll.exe") (Join-Path $Out "roll.exe") -Force
    Copy-Item (Join-Path $tmp "greet.dll") (Join-Path $Out "greet.dll") -Force
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

Write-Host "built (windows, amd64, MSVC cl):"
Write-Host "  $(Join-Path $Out 'roll.exe')"
Write-Host "  $(Join-Path $Out 'greet.dll')"
