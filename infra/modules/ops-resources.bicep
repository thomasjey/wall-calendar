// The kill switch (ADR-24): an action group that calls a Logic App, which
// stops each Function App through Azure Resource Manager with its own identity.

param location string
param alertEmail string

@description('Resource IDs of the Function Apps to stop.')
param siteIds array

var arm = environment().resourceManager // https://management.azure.com/ (with the trailing slash)

resource killSwitch 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-wallcal-kill-switch'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      parameters: {
        sites: { type: 'Array', defaultValue: [] }
      }
      triggers: {
        budget: { type: 'Request', kind: 'Http', inputs: { schema: {} } }
      }
      actions: {
        stop_each_app: {
          type: 'Foreach'
          foreach: '@parameters(\'sites\')'
          actions: {
            stop: {
              type: 'Http'
              inputs: {
                method: 'POST'
                uri: '@{concat(\'${arm}\', substring(item(), 1), \'/stop?api-version=2024-04-01\')}'
                authentication: { type: 'ManagedServiceIdentity', audience: arm }
              }
            }
          }
        }
      }
    }
    parameters: {
      sites: { value: siteIds }
    }
  }
}

resource killSwitchGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-wallcal-kill-switch'
  location: 'global'
  properties: {
    groupShortName: 'wallcalkill'
    enabled: true
    emailReceivers: [{ name: 'admin', emailAddress: alertEmail, useCommonAlertSchema: true }]
    logicAppReceivers: [
      {
        name: 'stop-function-apps'
        resourceId: killSwitch.id
        callbackUrl: listCallbackUrl('${killSwitch.id}/triggers/budget', '2019-05-01').value
        useCommonAlertSchema: true
      }
    ]
  }
}

output killSwitchPrincipalId string = killSwitch.identity.principalId
output killSwitchActionGroupId string = killSwitchGroup.id
