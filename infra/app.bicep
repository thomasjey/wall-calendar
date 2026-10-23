// App layer (DESIGN ADR-32): the Function App, its sign-in settings with the
// platform allowlist (layer 2), monitoring and alerts. Deployed by the GitHub
// workflow (Contributor on this resource group only) on top of foundation.bicep.
//
// Every parameter value comes from the environment's GitHub secrets, never
// from the repository, so none of them appear in the public workflow logs.

targetScope = 'resourceGroup'

@allowed(['dev', 'prod'])
param env string

param location string = resourceGroup().location

@description('Object IDs of the personal accounts allowed to sign in (platform allowlist, DESIGN §15.4). Never empty: an empty list would mean "everyone".')
@minLength(1)
@maxLength(10)
param allowedObjectIds array

@description('Enrolment (DESIGN §15.4): lifts the platform allowlist so a new person can sign in and see only their own ID. Needs the code-side enrolment window too.')
param enrolmentOpen bool = false

@description('Client ID of the web sign-in app registration.')
param signinClientId string

@description('Client ID of the cloud-sync app registration.')
param syncClientId string

@description('Where alerts are emailed.')
param alertEmail string

@description('Object ID of the administrator: expected to write the cloud config.')
param adminPrincipalId string

@minValue(0)
@maxValue(1)
param alwaysReady int = 0

@minValue(1)
@maxValue(4)
param maxInstances int = 4

@minValue(1)
@maxValue(16)
param perInstanceConcurrency int = 8

var suffix = take(uniqueString(resourceGroup().id), 6)
var functionAppName = 'wallcal-${env}-${suffix}'
var consumerTenant = '9188040d-6c67-4c5b-b112-36a304b66dad'
var signinSecretSetting = 'OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID'

// --- From the foundation layer ------------------------------------------------

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: 'stwallcal${env}${suffix}'
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: 'kv-wallcal-${env}-${suffix}'
}

resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'id-${functionAppName}-app'
}

resource signinIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'id-${functionAppName}-signin'
}

resource syncIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'id-${functionAppName}-sync'
}

// --- Monitoring (no event content is ever logged, DESIGN §17.7) ---------------

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${functionAppName}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 } // logging can't run away with the budget
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${functionAppName}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
  }
}

resource vaultAudit 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: vault
  name: 'audit-to-workspace'
  properties: {
    workspaceId: workspace.id
    logs: [{ categoryGroup: 'audit', enabled: true }]
  }
}

// --- The Function App ----------------------------------------------------------

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-${functionAppName}'
  location: location
  kind: 'functionapp'
  sku: { tier: 'FlexConsumption', name: 'FC1' }
  properties: { reserved: true }
}

resource site 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${appIdentity.id}': {}
      '${signinIdentity.id}': {}
      '${syncIdentity.id}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    siteConfig: {
      minTlsVersion: '1.3'
      scmMinTlsVersion: '1.3'
      http20Enabled: true
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'AzureWebJobsStorage__clientId', value: appIdentity.properties.clientId }
        { name: 'AzureWebJobsDisableHomepage', value: 'true' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
        { name: 'FWCAL_KEY_VAULT_URL', value: vault.properties.vaultUri }
        { name: 'FWCAL_BLOB_CONTAINER_URL', value: '${storage.properties.primaryEndpoints.blob}data' }
        { name: 'FWCAL_APP_IDENTITY_CLIENT_ID', value: appIdentity.properties.clientId }
        { name: 'FWCAL_SYNC_IDENTITY_CLIENT_ID', value: syncIdentity.properties.clientId }
        { name: 'FWCAL_SYNC_CLIENT_ID', value: syncClientId }
        // Built-in sign-in proves it is the web app with the sign-in identity, not a secret (ADR-26).
        { name: signinSecretSetting, value: signinIdentity.properties.clientId }
        { name: 'WEBSITE_AUTH_AAD_ALLOWED_TENANTS', value: consumerTenant }
      ]
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}deployment'
          authentication: { type: 'UserAssignedIdentity', userAssignedIdentityResourceId: appIdentity.id }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: maxInstances
        instanceMemoryMB: 512
        alwaysReady: alwaysReady > 0 ? [{ name: 'http', instanceCount: alwaysReady }] : []
        triggers: { http: { perInstanceConcurrency: perInstanceConcurrency } }
      }
      runtime: { name: 'python', version: '3.13' }
    }
  }
}

resource noFtp 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-04-01' = {
  parent: site
  name: 'ftp'
  properties: { allow: false }
}

resource noBasicScm 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-04-01' = {
  parent: site
  name: 'scm'
  properties: { allow: false }
}

// Layers 1 and 2 (DESIGN §15.4): sign-in required; personal accounts only; the platform allowlist.
resource auth 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: site
  name: 'authsettingsV2'
  properties: {
    platform: { enabled: true, runtimeVersion: '~1' }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: '${environment().authentication.loginEndpoint}${consumerTenant}/v2.0'
          clientId: signinClientId
          clientSecretSettingName: signinSecretSetting
        }
        validation: {
          defaultAuthorizationPolicy: {
            allowedApplications: [signinClientId]
            allowedPrincipals: enrolmentOpen ? {} : { identities: allowedObjectIds }
          }
        }
      }
    }
    login: {
      tokenStore: { enabled: false }
      cookieExpiration: { convention: 'FixedTime', timeToExpiration: '12:00:00' }
    }
    httpSettings: { requireHttps: true }
  }
}

// --- Alerts (DESIGN §17.7) -----------------------------------------------------

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-${functionAppName}'
  location: 'global'
  properties: {
    groupShortName: 'wallcal${env}'
    enabled: true
    emailReceivers: [{ name: 'admin', emailAddress: alertEmail, useCommonAlertSchema: true }]
  }
}

@description('Free: any write to the Function App settings, including sign-in and the platform allowlist (ADR-28).')
resource configChanged 'Microsoft.Insights/activityLogAlerts@2020-10-01' = {
  name: 'alert-${functionAppName}-config-changed'
  location: 'global'
  properties: {
    enabled: true
    scopes: [resourceGroup().id]
    condition: {
      allOf: [
        { field: 'category', equals: 'Administrative' }
        { field: 'operationName', equals: 'Microsoft.Web/sites/config/write' }
      ]
    }
    actions: { actionGroups: [{ actionGroupId: actionGroup.id }] }
  }
}

@description('No successful sync for 30 minutes.')
resource syncStale 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-${functionAppName}-sync-stale'
  location: location
  properties: {
    enabled: true
    severity: 2
    scopes: [insights.id]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT30M'
    criteria: {
      allOf: [
        {
          // The platform's own record of each run: it arrives even when Python log lines don't.
          query: 'traces | where message startswith "Executed \'Functions.sync\' (Succeeded" | summarize ok = count()'
          timeAggregation: 'Total'
          metricMeasureColumn: 'ok'
          operator: 'LessThan'
          threshold: 1
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [actionGroup.id] }
  }
}

var expectedVaultCallers = [appIdentity.properties.principalId, syncIdentity.properties.principalId, adminPrincipalId]

@description('A secret read or written by any identity other than the app, the sync and the administrator (ADR-28).')
resource vaultUnexpected 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-${functionAppName}-vault-unexpected'
  location: location
  properties: {
    enabled: true
    severity: 1
    scopes: [workspace.id]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: 'AzureDiagnostics | where ResourceProvider == "MICROSOFT.KEYVAULT" and OperationName startswith "Secret" | extend caller = tostring(column_ifexists("identity_claim_oid_g", "")) | where caller !in (dynamic(${string(expectedVaultCallers)})) | summarize n = count()'
          timeAggregation: 'Total'
          metricMeasureColumn: 'n'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [actionGroup.id] }
  }
}

@description('More than 5 failed requests in 15 minutes. Flex Consumption has no Http5xx site metric, so this uses Application Insights; requests refused by built-in sign-in never reach the code, so they are not counted.')
resource serverErrors 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${functionAppName}-5xx'
  location: 'global'
  properties: {
    severity: 2
    enabled: true
    scopes: [insights.id]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'failed-requests'
          criterionType: 'StaticThresholdCriterion'
          metricNamespace: 'microsoft.insights/components'
          metricName: 'requests/failed'
          operator: 'GreaterThan'
          threshold: 5
          timeAggregation: 'Count'
        }
      ]
    }
    actions: [{ actionGroupId: actionGroup.id }]
  }
}

output functionAppName string = site.name
output hostName string = site.properties.defaultHostName
