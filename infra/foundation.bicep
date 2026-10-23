// Foundation layer (DESIGN ADR-32): identities, Key Vault, storage and every
// role assignment. Deployed rarely, by the administrator, from the laptop
// (tools/azure/bootstrap.ps1). The pipeline deploys app.bicep on top of this
// and never needs permission to grant roles.
//
// First deployment: seedSecrets=true creates the two Key Vault secrets with
// placeholder values, so their per-secret role assignments can exist. Later
// deployments leave seedSecrets=false and never touch the secret values.

targetScope = 'resourceGroup'

@allowed(['dev', 'prod'])
param env string

param location string = resourceGroup().location

@description('Object ID of the administrator in the directory: the only identity that can write the cloud config.')
param adminPrincipalId string

@description('The repository as GitHub names it in its OIDC subject: owner@ownerId/name@repoId. The numeric IDs never change, so a renamed or re-created repository with the same name gets no trust (tools/azure/bootstrap.ps1 looks them up).')
param githubOidcRepo string

param seedSecrets bool = false

var suffix = take(uniqueString(resourceGroup().id), 6)
var functionAppName = 'wallcal-${env}-${suffix}'
var isProd = env == 'prod'

var roles = {
  contributor: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
  blobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  secretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  secretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
}

// --- Identities: one job each (ADR-26, ADR-27, ADR-32) ---------------------

@description('The app itself: host storage, the private container, reading the cloud config.')
resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${functionAppName}-app'
  location: location
}

@description('Trusted only by the web sign-in app registration (ADR-26).')
resource signinIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${functionAppName}-signin'
  location: location
}

@description('Trusted only by the cloud-sync app registration; reads and rotates the refresh token (ADR-27).')
resource syncIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${functionAppName}-sync'
  location: location
}

@description('Used only by the GitHub deploy workflow of this environment (OIDC, no stored secret).')
resource deployIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${functionAppName}-deploy'
  location: location
}

resource githubTrust 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: deployIdentity
  name: 'github-${env}'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubOidcRepo}:environment:${env}'
    audiences: ['api://AzureADTokenExchange']
  }
}

// --- Storage: no shared keys, private container -----------------------------

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stwallcal${env}${suffix}'
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'deployment'
  properties: { publicAccess: 'None' }
}

resource dataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'data'
  properties: { publicAccess: 'None' }
}

resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          // Pending consents are deleted on use; this removes any abandoned ones.
          name: 'expire-consent-state'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['data/consent/'] }
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 1 } } }
          }
        }
      ]
    }
  }
}

// --- Key Vault: RBAC, the refresh token and the cloud config only ------------

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-wallcal-${env}-${suffix}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: isProd ? 90 : 7
    // Purge protection can never be turned off again, so dev leaves it off to stay disposable.
    enablePurgeProtection: isProd ? true : null
    publicNetworkAccess: 'Enabled'
    networkAcls: { defaultAction: 'Allow', bypass: 'None' }
  }
}

resource configSeed 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (seedSecrets) {
  parent: vault
  name: 'fwcal-config'
  properties: {
    value: '# Placeholder: write the real cloud config (see deploy/AZURE.md). Until then everyone is refused.'
    contentType: 'application/toml'
  }
}

resource tokenSeed 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (seedSecrets) {
  parent: vault
  name: 'viewer-refresh-token'
  properties: {
    value: 'none'
    contentType: 'refresh-token'
  }
}

resource configSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = {
  parent: vault
  name: 'fwcal-config'
}

resource tokenSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = {
  parent: vault
  name: 'viewer-refresh-token'
}

// --- Role assignments ---------------------------------------------------------

resource appStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, appIdentity.id, roles.blobDataOwner)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobDataOwner)
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource appReadsConfig 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: configSecret
  name: guid(configSecret.id, appIdentity.id, roles.secretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.secretsUser)
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [configSeed]
}

resource adminWritesConfig 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: configSecret
  name: guid(configSecret.id, adminPrincipalId, roles.secretsOfficer)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.secretsOfficer)
    principalId: adminPrincipalId
    principalType: 'User'
  }
  dependsOn: [configSeed]
}

resource syncRotatesToken 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: tokenSecret
  name: guid(tokenSecret.id, syncIdentity.id, roles.secretsOfficer)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.secretsOfficer)
    principalId: syncIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [tokenSeed]
}

resource deployContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, deployIdentity.id, roles.contributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
    principalId: deployIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// --- Outputs (names and client IDs only; nothing secret) ---------------------

output functionAppName string = functionAppName
output hostName string = '${functionAppName}.azurewebsites.net'
output storageAccountName string = storage.name
output keyVaultName string = vault.name
output appIdentityName string = appIdentity.name
output signinIdentityName string = signinIdentity.name
output syncIdentityName string = syncIdentity.name
output signinIdentityPrincipalId string = signinIdentity.properties.principalId
output syncIdentityPrincipalId string = syncIdentity.properties.principalId
output deployIdentityClientId string = deployIdentity.properties.clientId
