[CmdletBinding()]
param(
    [string]$Server = "119.45.121.36",
    [string]$PublicOrigin = "https://www.yxciedu.com",
    [string]$RemoteUser = "root",
    [string]$IdentityFile = "",
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"
if ($PublicOrigin -notmatch '^https?://[A-Za-z0-9.-]+$') {
    throw "PublicOrigin must be an HTTP(S) origin without a path or trailing slash"
}
Set-StrictMode -Version Latest

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$WorkingDirectory = ""
    )

    if ($WorkingDirectory) {
        Push-Location -LiteralPath $WorkingDirectory
    }
    try {
        & $Command @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed (exit=$LASTEXITCODE): $Command $($Arguments -join ' ')"
        }
    }
    finally {
        if ($WorkingDirectory) {
            Pop-Location
        }
    }
}

function Get-NativeOutput {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$WorkingDirectory = ""
    )

    if ($WorkingDirectory) {
        Push-Location -LiteralPath $WorkingDirectory
    }
    try {
        $output = & $Command @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed (exit=$LASTEXITCODE): $Command $($Arguments -join ' ')"
        }
        return ($output | Out-String).Trim()
    }
    finally {
        if ($WorkingDirectory) {
            Pop-Location
        }
    }
}

function Assert-CommandExists {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command is not installed: $Name"
    }
}

if ($Server -notmatch "^[A-Za-z0-9.-]+$") {
    throw "Invalid server address"
}
if ($RemoteUser -notmatch "^[A-Za-z0-9_-]+$") {
    throw "Invalid remote user"
}

$repositoryRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$backendRoot = Join-Path $repositoryRoot "backend"
$frontendRoot = Join-Path $repositoryRoot "frontend\web"
$serverDeployScript = Join-Path $repositoryRoot "scripts\deploy-release.sh"

foreach ($commandName in @("git", "uv", "pnpm", "tar", "ssh", "scp")) {
    Assert-CommandExists -Name $commandName
}
if (-not (Test-Path -LiteralPath $serverDeployScript -PathType Leaf)) {
    throw "Missing server deployment script: $serverDeployScript"
}

$gitRoot = Get-NativeOutput -Command "git" -Arguments @("rev-parse", "--show-toplevel") -WorkingDirectory $repositoryRoot
if ([IO.Path]::GetFullPath($gitRoot) -ne $repositoryRoot) {
    throw "Run this script from the yuxin-ai-ops repository"
}

$branch = Get-NativeOutput -Command "git" -Arguments @("branch", "--show-current") -WorkingDirectory $repositoryRoot
if ($branch -ne "main") {
    throw "Production deployment requires the main branch. Current branch: $branch"
}

$workingTree = Get-NativeOutput -Command "git" -Arguments @("status", "--porcelain") -WorkingDirectory $repositoryRoot
if ($workingTree) {
    throw "The working tree is not clean. Commit and push all changes to main before deploying."
}

Write-Host "[1/7] Fetching origin/main..." -ForegroundColor Cyan
Invoke-NativeCommand -Command "git" -Arguments @("fetch", "origin", "main") -WorkingDirectory $repositoryRoot
$headCommit = Get-NativeOutput -Command "git" -Arguments @("rev-parse", "HEAD") -WorkingDirectory $repositoryRoot
$remoteCommit = Get-NativeOutput -Command "git" -Arguments @("rev-parse", "origin/main") -WorkingDirectory $repositoryRoot
if ($headCommit -ne $remoteCommit) {
    throw "Local HEAD does not match origin/main. Push or pull before deploying."
}
$releaseId = $headCommit.Substring(0, 8)

if (-not $SkipChecks) {
    Write-Host "[2/7] Verifying backend..." -ForegroundColor Cyan
    Invoke-NativeCommand -Command "uv" -Arguments @("run", "ruff", "check", ".") -WorkingDirectory $backendRoot
    Invoke-NativeCommand -Command "uv" -Arguments @("run", "pytest", "-q") -WorkingDirectory $backendRoot

    Write-Host "[3/7] Verifying frontend..." -ForegroundColor Cyan
    Invoke-NativeCommand -Command "pnpm" -Arguments @("test") -WorkingDirectory $frontendRoot
}
else {
    Write-Warning "Tests and static checks were skipped. The production frontend build will still run."
}

$temporaryRoot = [IO.Path]::GetFullPath(
    (Join-Path ([IO.Path]::GetTempPath()) ("yuxin-ai-ops-deploy-" + [Guid]::NewGuid().ToString("N")))
)
$systemTemporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
if (-not $systemTemporaryRoot.EndsWith([IO.Path]::DirectorySeparatorChar.ToString())) {
    $systemTemporaryRoot += [IO.Path]::DirectorySeparatorChar
}
if (-not $temporaryRoot.StartsWith($systemTemporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The deployment staging directory is outside the system temporary directory"
}

New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
try {
    Write-Host "[4/7] Building production frontend..." -ForegroundColor Cyan
    # Keep this script ASCII-only for Windows PowerShell 5.1 without a UTF-8 BOM.
    # Build in a fresh directory; never package a previous dist directory.
    $webBuildRoot = Join-Path $temporaryRoot "web"
    Invoke-NativeCommand -Command "pnpm" -Arguments @(
        "exec", "vite", "build", "--mode", "production", "--outDir", $webBuildRoot
    ) -WorkingDirectory $frontendRoot
    # Generate Vite auto-import declarations before checking TypeScript.
    Invoke-NativeCommand -Command "pnpm" -Arguments @("exec", "vue-tsc", "--noEmit") -WorkingDirectory $frontendRoot
    if (-not (Test-Path -LiteralPath (Join-Path $webBuildRoot "index.html") -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $webBuildRoot "js") -PathType Container)) {
        throw "Production build did not generate a fresh index.html and js directory. Deployment aborted."
    }

    $sourceArchiveName = "yuxin-ai-ops-$releaseId.tar.gz"
    $webArchiveName = "yuxin-ai-ops-web-$releaseId.tar.gz"
    $sourceArchive = Join-Path $temporaryRoot $sourceArchiveName
    $webArchive = Join-Path $temporaryRoot $webArchiveName
    $checksumsFile = Join-Path $temporaryRoot "checksums.sha256"
    $stagedDeployScript = Join-Path $temporaryRoot "deploy-release.sh"

    Write-Host "[5/7] Packaging commit $releaseId..." -ForegroundColor Cyan
    Invoke-NativeCommand -Command "git" -Arguments @(
        "archive",
        "--format=tar.gz",
        "--output=$sourceArchive",
        $headCommit
    ) -WorkingDirectory $repositoryRoot
    Invoke-NativeCommand -Command "tar" -Arguments @(
        "-czf",
        $webArchive,
        "-C",
        $webBuildRoot,
        "."
    )

    $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceArchive).Hash.ToLowerInvariant()
    $webHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $webArchive).Hash.ToLowerInvariant()
    $utf8WithoutBom = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText(
        $checksumsFile,
        "$sourceHash  $sourceArchiveName`n$webHash  $webArchiveName`n",
        $utf8WithoutBom
    )
    $normalizedDeployScript = [IO.File]::ReadAllText($serverDeployScript).Replace("`r`n", "`n")
    [IO.File]::WriteAllText($stagedDeployScript, $normalizedDeployScript, $utf8WithoutBom)

    if (-not $IdentityFile) {
        $userProfile = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
        $IdentityFile = Join-Path $userProfile ".ssh\yuxin_ai_ops_deploy_ed25519"
    }
    $resolvedIdentityFile = [IO.Path]::GetFullPath($IdentityFile)
    if (-not (Test-Path -LiteralPath $resolvedIdentityFile -PathType Leaf)) {
        throw "Deployment key not found: $resolvedIdentityFile"
    }

    $sshOptions = @(
        "-i", $resolvedIdentityFile,
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10"
    )
    $remoteTarget = "$RemoteUser@$Server"
    $remoteIncoming = "/data/stacks/yuxin-ai-ops/incoming/$releaseId"

    Write-Host "[6/7] Uploading release artifacts..." -ForegroundColor Cyan
    Invoke-NativeCommand -Command "ssh" -Arguments @(
        $sshOptions + @($remoteTarget, "mkdir -p '$remoteIncoming' && chmod 700 '$remoteIncoming'")
    )
    Invoke-NativeCommand -Command "scp" -Arguments @(
        $sshOptions + @(
            $sourceArchive,
            $webArchive,
            $checksumsFile,
            $stagedDeployScript,
            "${remoteTarget}:${remoteIncoming}/"
        )
    )

    Write-Host "[7/7] Running backup, migration, and frontend/backend switch..." -ForegroundColor Cyan
    $remoteCommand = "chmod 700 '$remoteIncoming/deploy-release.sh' && '$remoteIncoming/deploy-release.sh' '$releaseId' '$PublicOrigin'"
    Invoke-NativeCommand -Command "ssh" -Arguments @($sshOptions + @($remoteTarget, $remoteCommand))

    Write-Host "Deployment complete: $releaseId" -ForegroundColor Green
    Write-Host "Operations URL: $PublicOrigin/web/" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $verifiedTemporaryRoot = [IO.Path]::GetFullPath($temporaryRoot)
        if ($verifiedTemporaryRoot.StartsWith($systemTemporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $verifiedTemporaryRoot -Recurse -Force
        }
    }
}
