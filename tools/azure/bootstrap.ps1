# One-time setup of an environment (DESIGN ADR-32), run by the administrator
# from the laptop, signed in with `az login` (MFA). Safe to run again: every
# step checks what already exists.
#
#   .\tools\azure\bootstrap.ps1 -Env dev -Subscription <id> -FirstRun   # first time: seeds the Key Vault secrets
#   .\tools\azure\bootstrap.ps1 -Env prod -Subscription <id>
#   .\tools\azure\bootstrap.ps1 -Ops -Subscription <id>                 # budget and kill switch (once)
#
# It deploys foundation.bicep (after showing what-if and asking), creates the
# two app registrations with managed-identity trust and no secrets, and sets
# up the GitHub environment and its secrets. It prints names, never secret
# values. Personal values (allowed object IDs, alert email) are asked for and
# stored only as GitHub secrets.
param(
    [ValidateSet('dev', 'prod')][string]$Env,
    [Parameter(Mandatory)][string]$Subscription,
    [string]$Location = 'westus2',
    [string]$Repo = 'thomasjey/wall-calendar',
    [switch]$FirstRun,
    [switch]$Ops
)
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$consumerTenant = '9188040d-6c67-4c5b-b112-36a304b66dad'
$graphApi = '00000003-0000-0000-c000-000000000000'
$calendarsReadScopeId = '465a38f9-76ea-45b9-9f34-9e8b0d4b0b42'  # not $calendarsRead: names are case-insensitive

function Invoke-Az {
    $out = & az @args
    if ($LASTEXITCODE -ne 0) { throw "az $($args[0..2] -join ' ') ... failed (exit $LASTEXITCODE)" }
    return $out
}

function Confirm-Step([string]$question) {
    $answer = Read-Host "$question (y/N)"
    if ($answer -ne 'y') { throw 'Stopped; nothing more was changed.' }
}

function Write-TempJson($object) {
    $path = Join-Path ([IO.Path]::GetTempPath()) ("wallcal-" + [guid]::NewGuid() + '.json')
    $object | ConvertTo-Json -Depth 10 -Compress | Set-Content -Encoding ascii $path
    return $path
}

function Invoke-Graph([string]$method, [string]$url, $body) {
    $file = Write-TempJson $body
    try { Invoke-Az rest --method $method --url $url --body "@$file" --headers 'Content-Type=application/json' --output none }
    finally { Remove-Item $file }
}

Invoke-Az account set --subscription $Subscription | Out-Null
$tenant = Invoke-Az account show --query tenantId -o tsv

if ($Ops) {
    $email = Read-Host 'Email address for budget alerts'
    $params = Write-TempJson @{ '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'; contentVersion = '1.0.0.0'; parameters = @{ alertEmail = @{ value = $email }; location = @{ value = $Location } } }
    try {
        Invoke-Az deployment sub what-if --location $Location --template-file "$root\infra\ops.bicep" --parameters "@$params" --result-format ResourceIdOnly
        Confirm-Step 'Deploy the budget and kill switch?'
        Invoke-Az deployment sub create --location $Location --template-file "$root\infra\ops.bicep" --parameters "@$params" --output none
    } finally { Remove-Item $params }
    Write-Output 'Budget ($10) and kill switch deployed.'
    return
}
if (-not $Env) { throw 'Give -Env dev or -Env prod (or -Ops).' }

Write-Output "Registering resource providers..."
foreach ($ns in 'Microsoft.Web', 'Microsoft.Storage', 'Microsoft.KeyVault', 'Microsoft.ManagedIdentity', 'Microsoft.Insights', 'Microsoft.OperationalInsights', 'Microsoft.Logic', 'Microsoft.Consumption') {
    Invoke-Az provider register --namespace $ns --wait | Out-Null
}

$rg = "rg-wallcal-$Env"
Invoke-Az group create --name $rg --location $Location --tags "app=wall-calendar" "env=$Env" --output none
$admin = Invoke-Az ad signed-in-user show --query id -o tsv
# GitHub's OIDC subject names the repository with its permanent IDs: owner@ownerId/name@repoId.
$repoInfo = gh api "repos/$Repo" | ConvertFrom-Json
$oidcRepo = "$($repoInfo.owner.login)@$($repoInfo.owner.id)/$($repoInfo.name)@$($repoInfo.id)"
if ($oidcRepo -notmatch '^[^@/]+@\d+/[^@/]+@\d+$') { throw "Could not read the repository IDs from GitHub." }

if ($FirstRun) {
    # -FirstRun seeds placeholder secrets; never let it overwrite a real config or token.
    $existingVault = Invoke-Az keyvault list --resource-group $rg --query '[0].name' -o tsv
    if ($existingVault) {
        # The administrator can read only this one secret, so ask for it directly.
        $null = az keyvault secret show --vault-name $existingVault --name fwcal-config --query id -o tsv 2>$null
        if ($LASTEXITCODE -eq 0) { throw "The secrets in $existingVault already exist: run again without -FirstRun." }
    }
}

# --- 1. Foundation ---------------------------------------------------------
$params = Write-TempJson @{ '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'; contentVersion = '1.0.0.0'; parameters = @{ env = @{ value = $Env }; adminPrincipalId = @{ value = $admin }; githubOidcRepo = @{ value = $oidcRepo }; seedSecrets = @{ value = [bool]$FirstRun } } }
try {
    Invoke-Az deployment group what-if --resource-group $rg --template-file "$root\infra\foundation.bicep" --parameters "@$params" --result-format ResourceIdOnly
    Confirm-Step "Deploy the foundation for ${Env}?"
    $out = Invoke-Az deployment group create --resource-group $rg --name foundation --template-file "$root\infra\foundation.bicep" --parameters "@$params" --query properties.outputs -o json | ConvertFrom-Json
} finally { Remove-Item $params }
$hostName = $out.hostName.value
Write-Output "Foundation deployed. Function App will be https://$hostName"

# --- 2. App registrations: personal accounts only, managed-identity trust, no secrets
function Set-AppRegistration([string]$name, [string]$redirect, [string]$identityPrincipalId, [switch]$IdTokens, [switch]$CalendarsRead) {
    $appId = Invoke-Az ad app list --display-name $name --query '[0].appId' -o tsv
    if (-not $appId) {
        $appId = Invoke-Az ad app create --display-name $name --query appId -o tsv
        Write-Output "  created $name"
    }
    $objectId = Invoke-Az ad app show --id $appId --query id -o tsv
    $url = "https://graph.microsoft.com/v1.0/applications/$objectId"
    # Personal-account apps need v2 access tokens before the audience can change (R1).
    Invoke-Graph patch $url @{ api = @{ requestedAccessTokenVersion = 2 } }
    Invoke-Graph patch $url @{ signInAudience = 'PersonalMicrosoftAccount' }
    Invoke-Graph patch $url @{ web = @{ redirectUris = @($redirect); implicitGrantSettings = @{ enableIdTokenIssuance = [bool]$IdTokens; enableAccessTokenIssuance = $false } } }
    if ($CalendarsRead) {
        Invoke-Graph patch $url @{ requiredResourceAccess = @(@{ resourceAppId = $graphApi; resourceAccess = @(@{ id = $calendarsReadScopeId; type = 'Scope' }) }) }
    }
    $fic = Invoke-Az ad app federated-credential list --id $appId --query "[?name=='managed-identity'].name" -o tsv
    if (-not $fic) {
        $file = Write-TempJson @{ name = 'managed-identity'; issuer = "https://login.microsoftonline.com/$tenant/v2.0"; subject = $identityPrincipalId; audiences = @('api://AzureADTokenExchange'); description = "$name trusts its managed identity (no secret)" }
        try { Invoke-Az ad app federated-credential create --id $appId --parameters "@$file" --output none } finally { Remove-Item $file }
    }
    $creds = Invoke-Az ad app show --id $appId --query '{s:length(passwordCredentials), c:length(keyCredentials)}' -o json | ConvertFrom-Json
    if ($creds.s -ne 0 -or $creds.c -ne 0) { throw "$name has a secret or certificate; remove it (DESIGN ADR-26, ADR-27)." }
    return $appId
}

Write-Output 'App registrations...'
$signin = Set-AppRegistration "wall-calendar-$Env-signin" "https://$hostName/.auth/login/aad/callback" $out.signinIdentityPrincipalId.value -IdTokens
$sync = Set-AppRegistration "wall-calendar-$Env-sync" "https://$hostName/manage/consent/callback" $out.syncIdentityPrincipalId.value -CalendarsRead
Write-Output '  both: personal accounts only, 0 secrets, 0 certificates, trust in one managed identity each'

# --- 3. GitHub environment and secrets (secrets are masked in the public logs)
Write-Output "GitHub environment '$Env'..."
$me = gh api user --jq .id
if ($Env -eq 'prod') {
    $body = Write-TempJson @{ reviewers = @(@{ type = 'User'; id = [int]$me }); deployment_branch_policy = @{ protected_branches = $false; custom_branch_policies = $true } }
    $pattern = @{ name = 'v*'; type = 'tag' }
} else {
    $body = Write-TempJson @{ deployment_branch_policy = @{ protected_branches = $false; custom_branch_policies = $true } }
    $pattern = @{ name = 'main'; type = 'branch' }
}
try { gh api -X PUT "repos/$Repo/environments/$Env" --input $body | Out-Null } finally { Remove-Item $body }
$existing = gh api "repos/$Repo/environments/$Env/deployment-branch-policies" --jq '.branch_policies[].name'
if ($existing -notcontains $pattern.name) {
    $body = Write-TempJson $pattern
    try { gh api -X POST "repos/$Repo/environments/$Env/deployment-branch-policies" --input $body | Out-Null } finally { Remove-Item $body }
}
$values = @{
    AZURE_CLIENT_ID = $out.deployIdentityClientId.value; AZURE_TENANT_ID = $tenant; AZURE_SUBSCRIPTION_ID = $Subscription
    SIGNIN_CLIENT_ID = $signin; SYNC_CLIENT_ID = $sync; ADMIN_PRINCIPAL_ID = $admin
}
foreach ($k in $values.Keys) { $values[$k] | gh secret set $k --env $Env --repo $Repo | Out-Null }
gh variable set DEPLOY_ENABLED --body true --repo $Repo | Out-Null  # lets the deploy workflow run
$have = gh secret list --env $Env --repo $Repo --json name --jq '.[].name'
foreach ($k in 'ALLOWED_OBJECT_IDS', 'ALERT_EMAIL') {
    if ($have -notcontains $k) { Write-Output "  still to set (personal, entered by you): gh secret set $k --env $Env --repo $Repo" }
}
Write-Output ''
Write-Output "Done. Next for $Env (deploy/AZURE.md):"
Write-Output "  1. Write the cloud config:   .\tools\azure\put_config.ps1 -Env $Env -File <your config.toml>"
Write-Output "  2. Deploy:                    run the 'deploy' workflow (dev: push to main; prod: a v* tag, then approve)"
Write-Output "  3. Connect the calendar:      open https://$hostName/manage/consent and sign in as the viewer account"
