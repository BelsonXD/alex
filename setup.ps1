# ALEX setup for Windows PowerShell 5.1 and PowerShell 7.
# Selects Python 3.12, then 3.13, then 3.11. Never uses 3.14 or 3.15.
# Recreates .venv when it was built with an unsupported interpreter.
# Installs dependencies from binary wheels only, builds the UI, then launches ALEX.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Supported = @("3.12", "3.13", "3.11")
$Download = "https://www.python.org/downloads/windows/"
$script:Rejected = @()

function Get-PythonVersionText {
    param(
        [string]$Exe,
        [string[]]$Prefix
    )
    $argList = @()
    if ($Prefix) { $argList += $Prefix }
    $argList += @("-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])")
    try {
        $output = & $Exe @argList 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
    $line = @($output)[-1]
    if (-not $line) { return $null }
    return $line.Trim()
}

function Test-SupportedVersion {
    param([string]$VersionText)
    if (-not $VersionText) { return $false }
    $parts = $VersionText.Split(".")
    if ($parts.Length -lt 2) { return $false }
    $key = $parts[0] + "." + $parts[1]
    return $Supported -contains $key
}

function Add-RejectedVersion {
    param([string]$Label, [string]$VersionText)
    if (-not $VersionText) { return }
    if (Test-SupportedVersion $VersionText) { return }
    $script:Rejected += @("$Label $VersionText")
}

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($minor in $Supported) {
            $version = Get-PythonVersionText -Exe "py" -Prefix @("-$minor")
            if (Test-SupportedVersion $version) {
                return @{ Exe = "py"; Prefix = @("-$minor"); Version = $version }
            }
        }
        foreach ($minor in @("-3.15", "-3.14", "-3.10", "-3.9", "-3")) {
            $version = Get-PythonVersionText -Exe "py" -Prefix @($minor)
            Add-RejectedVersion -Label "py $minor" -VersionText $version
        }
    }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $version = Get-PythonVersionText -Exe $name -Prefix @()
        if (Test-SupportedVersion $version) {
            return @{ Exe = $name; Prefix = @(); Version = $version }
        }
        Add-RejectedVersion -Label $name -VersionText $version
    }
    return $null
}

function Show-PythonHelp {
    Write-Host ""
    Write-Host "ALEX could not find Python 3.12, 3.13, or 3.11."
    if ($script:Rejected.Count -gt 0) {
        Write-Host "Found a Python that ALEX will not use:"
        foreach ($item in $script:Rejected) { Write-Host "  $item" }
        Write-Host ""
        Write-Host "Python 3.14 and 3.15 (including pre-releases) do not have Windows wheels"
        Write-Host "for every library ALEX needs. pip then tries to compile PyYAML and stops with:"
        Write-Host "  Microsoft Visual C++ 14.0 or greater is required"
        Write-Host "You do not need Visual C++. Install Python 3.12 next to the version you have."
    } else {
        Write-Host "Python does not appear to be installed."
    }
    Write-Host ""
    Write-Host "Download Python 3.12 (64-bit Windows installer):"
    Write-Host "  $Download"
    Write-Host "In the installer, check 'py launcher' and 'Add python.exe to PATH'."
    Write-Host "Then run start.bat again. It will choose py -3.12."
    Write-Host ""
}

$python = Find-Python
if (-not $python) {
    Show-PythonHelp
    exit 1
}
Write-Host ("Using Python " + $python.Version + " (" + $python.Exe + " " + ($python.Prefix -join " ") + ")")

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "Node.js was not found. It is only needed to build the interface."
    Write-Host "Install Node.js 20 LTS or newer from https://nodejs.org/en/download"
    exit 1
}
$nodeVersion = & node -p "process.versions.node"
Write-Host "Using Node.js $nodeVersion"

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $venvVersion = Get-PythonVersionText -Exe $venvPython -Prefix @()
    if (-not (Test-SupportedVersion $venvVersion)) {
        Write-Host "Removing .venv because it was created with Python $venvVersion."
        Write-Host "ALEX will recreate it with Python $($python.Version)."
        Remove-Item -LiteralPath (Join-Path $Root ".venv") -Recurse -Force
    } else {
        Write-Host "Virtual environment already uses Python $venvVersion."
    }
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating the Python virtual environment..."
    $venvArgs = @()
    $venvArgs += $python.Prefix
    $venvArgs += @("-m", "venv", ".venv")
    & $python.Exe @venvArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$venvCheck = Get-PythonVersionText -Exe $venvPython -Prefix @()
if (-not (Test-SupportedVersion $venvCheck)) {
    Write-Host "The new virtual environment is Python $venvCheck, which is not supported."
    Show-PythonHelp
    exit 1
}

$reqFile = Join-Path $Root "requirements.txt"
$reqStamp = Join-Path $Root ".venv\.alex-reqs.sha256"
$reqHash = (Get-FileHash -Algorithm SHA256 $reqFile).Hash
$needPip = $true
if (Test-Path $reqStamp) {
    $previous = (Get-Content -Raw $reqStamp).Trim()
    if ($previous -eq $reqHash) { $needPip = $false }
}
if ($needPip) {
    Write-Host "Installing Python packages from binary wheels..."
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $venvPython -m pip install --disable-pip-version-check --prefer-binary -r $reqFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "pip could not install every package from a Windows wheel."
        Write-Host "ALEX will not compile source packages, so Visual C++ is not required."
        Write-Host "Use Python 3.12 from $Download and run start.bat again."
        exit $LASTEXITCODE
    }
    Set-Content -Path $reqStamp -Value $reqHash -Encoding ascii
} else {
    Write-Host "Python packages already match requirements.txt."
}

$DataDir = Join-Path $env:LOCALAPPDATA "ALEX"
if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir | Out-Null }
$UserEnv = Join-Path $DataDir ".env"
if (-not (Test-Path $UserEnv)) {
    Copy-Item (Join-Path $Root ".env.example") $UserEnv
    Write-Host "Created $UserEnv"
    Write-Host "Keys and memories stay in $DataDir when you update ALEX."
} else {
    Write-Host "Keeping existing settings and memories in $DataDir"
}

$frontend = Join-Path $Root "frontend"
$lock = Join-Path $frontend "package-lock.json"
$lockStamp = Join-Path $frontend ".alex-lock.sha256"
$distIndex = Join-Path $frontend "dist\index.html"
$needNode = -not (Test-Path (Join-Path $frontend "node_modules"))
$needBuild = -not (Test-Path $distIndex)
if (Test-Path $lock) {
    $lockHash = (Get-FileHash -Algorithm SHA256 $lock).Hash
    if ((Test-Path $lockStamp) -and ((Get-Content -Raw $lockStamp).Trim() -eq $lockHash) -and (Test-Path (Join-Path $frontend "node_modules"))) {
        $needNode = $false
    } else {
        $needNode = $true
    }
} 
if ($needBuild -or $needNode) {
    Push-Location $frontend
    if ($needNode) {
        Write-Host "Installing interface packages..."
        if (Test-Path $lock) { npm ci } else { npm install }
        if ($LASTEXITCODE -ne 0) { Pop-Location; exit $LASTEXITCODE }
        if (Test-Path $lock) { Set-Content -Path $lockStamp -Value (Get-FileHash -Algorithm SHA256 $lock).Hash -Encoding ascii }
    } else {
        Write-Host "Interface packages already installed."
    }
    Write-Host "Building the interface..."
    npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; exit $LASTEXITCODE }
    Pop-Location
} else {
    Write-Host "Interface already built."
}

Write-Host "Launching ALEX..."
& $venvPython (Join-Path $Root "start.py")
exit $LASTEXITCODE
