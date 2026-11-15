# Run locally from this repository, on the owner's Windows PC.
# Browser OAuth consent is required only if its existing local token fails exact live channel-ID verification.
# Never paste a token, OAuth URL, secret or authorization code into chat.
param(
    [switch] $AllFour
)
$ErrorActionPreference = 'Stop'
$Repo = 'emirhankaya985-cloud/auto-video-publisher'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClientPath = Join-Path $Root 'client_secrets.json'
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python not installed or not on PATH.'
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI missing; install gh and authenticate to the 985 account first.'
}
$Login = (& gh api user --jq '.login')
if ($LASTEXITCODE -ne 0 -or $Login.Trim() -ne 'emirhankaya985-cloud') {
    throw 'GitHub CLI is not logged into emirhankaya985-cloud; no secrets were written.'
}
& python -c 'import google_auth_oauthlib, google.auth'
if ($LASTEXITCODE -ne 0) {
    throw 'Missing Google OAuth Python libraries. In this folder, run: python -m pip install --require-hashes -r requirements.txt'
}
$Targets = @(
    @{ Route = 'channel1'; File = 'token_channel1.json'; Secret = 'TOKEN_CHANNEL1_JSON' },
    @{ Route = 'channel2'; File = 'token_channel2.json'; Secret = 'TOKEN_CHANNEL2_JSON' }
)
if ($AllFour) {
    $Targets += @(
        @{ Route = 'daily_laugh'; File = 'token_daily_laugh_lab.json'; Secret = 'TOKEN_DAILY_LAUGH_LAB_JSON' },
        @{ Route = 'gonle_dusen'; File = 'token_gonle_dusen.json'; Secret = 'TOKEN_GONLE_DUSEN_JSON' }
    )
}
foreach ($Target in $Targets) {
    # First use an existing locally authorized-user token if a real Google
    # channels.list GET proves that it belongs to this exact route's channel.
    # This avoids unnecessary consent and refresh-token rotation.
    & python (Join-Path $Root 'youtube_local_token_probe.py') $Target.Route
    if ($LASTEXITCODE -ne 0) {
        if (-not (Test-Path -LiteralPath $ClientPath -PathType Leaf)) {
            throw ('Local token not verified for ' + $Target.Route + '; missing correct Desktop OAuth client_secrets.json. No GitHub secret updated.')
        }
        # Only now ask the owner for browser consent. The old token remains
        # untouched until a new refresh token and exact channel GET are verified.
        & python (Join-Path $Root 'youtube_authorize_channel.py') $Target.Route '--renew'
        if ($LASTEXITCODE -ne 0) {
            throw ('Authorization failed for ' + $Target.Route + '; existing GitHub secrets unchanged for this target.')
        }
    }
    $File = Join-Path $Root $Target.File
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
        throw ('Verified local token file missing for ' + $Target.Route)
    }
    # Stdin avoids putting the raw JSON in a shell argument or command history.
    Get-Content -LiteralPath $File -Raw | & gh secret set $Target.Secret --repo $Repo
    if ($LASTEXITCODE -ne 0) {
        throw ('Could not update GitHub secret for ' + $Target.Route)
    }
    & gh workflow run 'youtube_readonly_connection.yml' --repo $Repo --ref main -f ('channel=' + $Target.Route)
    if ($LASTEXITCODE -ne 0) {
        throw ('GitHub secret updated, but read-only verification could not be queued for ' + $Target.Route)
    }
    Write-Output ('Uploaded credential and queued no-upload check for ' + $Target.Route)
}
Write-Output 'No upload or publishing flag was enabled. Check each Actions run for a verified exact channel ID.'
