// The kill switch (ADR-24): an action group that calls a Logic App, which
// stops each Function App through Azure Resource Manager with its own identity.

param location string
param alertEmail string

@description('Resource IDs of the Function Apps to stop.')
param siteIds array

@description('Function Apps to watch for a flood: { env, siteId, stop }. stop: false only emails.')
param floodWatch array

param floodThreshold int

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

// Email only, for dev's flood alert (load tests there are expected).
resource emailGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-wallcal-email'
  location: 'global'
  properties: {
    groupShortName: 'wallcalmail'
    enabled: true
    emailReceivers: [{ name: 'admin', emailAddress: alertEmail, useCommonAlertSchema: true }]
  }
}

// The fast brake (DESIGN §17.8): the budget sees costs hours late, so a flood
// is also caught from the platform's own execution counts, which arrive within
// minutes and don't depend on Application Insights (whose daily cap a flood
// can exhaust). On-demand and always-ready executions are counted separately;
// either one over the threshold trips it. Dev has no always-ready instance.
// Kept here, not in the app deployment, so the deploy pipeline can't disable it.
var floodRules = flatten(map(floodWatch, w => concat(
  [{ env: w.env, siteId: w.siteId, stop: w.stop, metric: 'OnDemandFunctionExecutionCount', kind: 'on-demand' }],
  w.env == 'prod' ? [{ env: w.env, siteId: w.siteId, stop: w.stop, metric: 'AlwaysReadyFunctionExecutionCount', kind: 'always-ready' }] : []
)))

resource flood 'Microsoft.Insights/metricAlerts@2018-03-01' = [for r in floodRules: {
  name: 'alert-wallcal-${r.env}-flood-${r.kind}'
  location: 'global'
  properties: {
    description: r.stop ? 'Far more executions than normal use: the kill switch stops the Function Apps.' : 'Far more executions than normal use (dev: email only).'
    severity: 1
    enabled: true
    scopes: [r.siteId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'executions'
          criterionType: 'StaticThresholdCriterion'
          metricNamespace: 'Microsoft.Web/sites'
          metricName: r.metric
          operator: 'GreaterThan'
          threshold: floodThreshold
          timeAggregation: 'Total'
        }
      ]
    }
    actions: [{ actionGroupId: r.stop ? killSwitchGroup.id : emailGroup.id }]
  }
}]
