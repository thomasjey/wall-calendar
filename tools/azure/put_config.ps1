# Writes the cloud config (DESIGN ADR-28, ADR-31) to the environment's Key
# Vault, after validating it locally. Only the administrator can write this
# secret; the app can only read it. The file stays on the laptop (it is
# gitignored like every *.toml except the example).
#
#   .\tools\azure\put_config.ps1 -Env dev -File $env:APPDATA\fwcal\cloud-dev.toml
param(
    [Parameter(Mandatory)][ValidateSet('dev', 'prod')][string]$Env,
    [Parameter(Mandatory)][string]$File
)
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'

Push-Location $root
try { & $python -m fwcal.cloud.settings $File } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'The config is invalid; nothing was uploaded.' }

$vault = az keyvault list --resource-group "rg-wallcal-$Env" --query '[0].name' -o tsv
if (-not $vault) { throw "No Key Vault in rg-wallcal-$Env (run bootstrap.ps1 first)." }
az keyvault secret set --vault-name $vault --name fwcal-config --file $File --content-type application/toml --output none
if ($LASTEXITCODE -ne 0) { throw 'Upload failed.' }
Write-Output "Uploaded to $vault as a new version of fwcal-config. The app picks it up within 5 minutes."
