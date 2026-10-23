// Cost controls (DESIGN §17.8, ADR-24): the $10 monthly budget with email
// alerts, and a kill switch that stops the dev and prod Function Apps when
// actual cost reaches 100%. Deployed once, by the administrator, at
// subscription scope (tools/azure/bootstrap.ps1 -Ops). The wall at home is
// unaffected by the kill switch; restarting is a manual step (deploy/AZURE.md).

targetScope = 'subscription'

param location string = 'westus2'

@description('Where budget alerts are emailed.')
param alertEmail string

param amount int = 10

@description('First day of the current month, yyyy-MM-01: the budget starts here.')
param startDate string = '${utcNow('yyyy-MM')}-01'

param environments array = ['dev', 'prod']

var appResourceGroups = [for e in environments: 'rg-wallcal-${e}']
var siteIds = [for e in environments: '${subscription().id}/resourceGroups/rg-wallcal-${e}/providers/Microsoft.Web/sites/wallcal-${e}-${take(uniqueString('${subscription().id}/resourceGroups/rg-wallcal-${e}'), 6)}']

resource opsGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-wallcal-ops'
  location: location
}

module ops 'modules/ops-resources.bicep' = {
  scope: opsGroup
  name: 'ops-resources'
  params: {
    location: location
    alertEmail: alertEmail
    siteIds: siteIds
  }
}

// The kill switch may stop (and start) sites in the two app resource groups, nothing else.
module stopRole 'modules/stop-role.bicep' = [for rg in appResourceGroups: {
  scope: resourceGroup(rg)
  name: 'kill-switch-role-${rg}'
  params: { principalId: ops.outputs.killSwitchPrincipalId }
}]

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: 'budget-wallcal'
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: { startDate: startDate }
    notifications: {
      actual50: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 50, thresholdType: 'Actual', contactEmails: [alertEmail] }
      actual80: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, thresholdType: 'Actual', contactEmails: [alertEmail] }
      forecast100: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Forecasted', contactEmails: [alertEmail] }
      actual100KillSwitch: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: [alertEmail]
        contactGroups: [ops.outputs.killSwitchActionGroupId]
      }
    }
  }
}
