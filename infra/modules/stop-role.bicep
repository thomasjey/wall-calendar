// Lets the kill switch stop and start sites in one resource group (Website Contributor).

param principalId string

var websiteContributor = 'de139f84-1756-47ae-9be6-808fbbe84772'

resource stopper 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, principalId, websiteContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', websiteContributor)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
