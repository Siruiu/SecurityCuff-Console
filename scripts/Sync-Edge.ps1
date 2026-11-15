[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]*$')]
    [string]$Remote = 'edge',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._/-]*$')]
    [string]$Branch = 'dev'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryRoot
try {
    $changes = @(git status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read local Git status.' }
    if ($changes.Count -gt 0) {
        throw 'The working tree has uncommitted files. Commit or stash them before syncing.'
    }

    $revision = git rev-parse --verify HEAD
    if ($LASTEXITCODE -ne 0) { throw 'The repository needs an initial commit.' }
    $revision = $revision.Trim()

    git check-ref-format --branch $Branch | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Invalid target branch.' }

    $remoteUrl = git remote get-url --push $Remote
    if ($LASTEXITCODE -ne 0) { throw "Cannot read remote: $Remote" }
    if ($remoteUrl -notmatch '^(?<SshAlias>[A-Za-z0-9][A-Za-z0-9_.-]*):(?<RepoPath>/[A-Za-z0-9_./-]+\.git)$') {
        throw 'Expected a remote URL of the form ssh-alias:/absolute/path/repository.git.'
    }
    $edgeAlias = $Matches.SshAlias
    $deviceRepository = $Matches.RepoPath
    $deviceWorktree = $deviceRepository.Substring(0, $deviceRepository.Length - 4) + '-dev'

    # Pass Python through stdin to avoid PowerShell/native SSH shell-quoting differences.
    $deviceProgram = @"
import os
import subprocess
import sys

worktree = '$deviceWorktree'
branch = '$Branch'
expected_origin = '$deviceRepository'
revision = '$revision'

def git(*arguments):
    return subprocess.check_output(['git', '-C', worktree, *arguments], text=True).strip()

def require(condition, message):
    if not condition:
        sys.exit(message)

require(os.path.isdir(os.path.join(worktree, '.git')), 'Device worktree is missing.')
require(not git('status', '--porcelain', '--untracked-files=all'), 'Device worktree has uncommitted files.')
require(git('branch', '--show-current') == branch, 'Device branch does not match.')
require(git('remote', 'get-url', 'origin') == expected_origin, 'Device origin does not match.')
if sys.argv[1] == 'update':
    subprocess.run(['git', '-C', worktree, 'pull', '--ff-only'], check=True)
    require(git('rev-parse', 'HEAD') == revision, 'Device revision does not match.')
    require(not git('status', '--porcelain', '--untracked-files=all'), 'Device worktree is not clean after update.')
"@

    $deviceProgram | ssh -o BatchMode=yes -o ConnectTimeout=15 $edgeAlias python3 - preflight
    if ($LASTEXITCODE -ne 0) {
        throw 'Device preflight failed. Check connectivity, working-tree changes, branch and origin.'
    }

    git push $Remote "HEAD:refs/heads/$Branch"
    if ($LASTEXITCODE -ne 0) { throw 'Push failed; no forced update was attempted.' }

    $deviceProgram | ssh -o BatchMode=yes -o ConnectTimeout=15 $edgeAlias python3 - update
    if ($LASTEXITCODE -ne 0) {
        throw 'Device update or revision verification failed. The receiving repository may already contain the commit.'
    }

    Write-Host "Synced $revision to ${edgeAlias}:$deviceWorktree"
}
finally {
    Pop-Location
}
