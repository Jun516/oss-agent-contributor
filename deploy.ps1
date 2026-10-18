# Run locally on YOUR trusted Windows machine after reviewing all included files.
# GitHub authentication and repository creation cannot be delegated via current connector.
$ErrorActionPreference = 'Stop'
$repo = 'Jun516/oss-agent-contributor'

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git first.' }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'Install GitHub CLI first.' }
& gh auth status
if ($LASTEXITCODE -ne 0) { throw 'Authenticate with gh auth login --web first.' }

$login = (& gh api user --jq '.login').Trim()
if ($LASTEXITCODE -ne 0 -or $login -ne 'Jun516') { throw "GitHub identity mismatch: '$login'" }

Set-Location $PSScriptRoot
& git rev-parse --git-dir 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    & git init -b main
    if ($LASTEXITCODE -ne 0) { throw 'git init failed' }
    & git add .
    & git -c user.name=Jun516 -c user.email='Jun516@users.noreply.github.com' commit -m 'chore: add autonomous OSS contributor pipeline'
    if ($LASTEXITCODE -ne 0) { throw 'git commit failed' }
}
& gh repo view $repo 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    & gh repo create $repo --public --source . --remote origin --push
    if ($LASTEXITCODE -ne 0) { throw 'Repository creation or push failed' }
} else {
    Write-Host 'Repository already exists. No changes were pushed automatically.'
    Write-Host 'Review git status/diff and push explicitly after checking remote.'
}
Write-Host 'Next: configure OPENAI_API_KEY and OSS_BOT_TOKEN in GitHub Actions Secrets and manually dispatch the workflow.'
Write-Host 'WARNING: Autonomous publishing is enabled after secrets are configured unless PAUSE_AUTOPUBLISH=true.'
