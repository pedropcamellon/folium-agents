resource "azurerm_resource_group" "chat_model" {
  name     = var.resource_group_name
  location = var.location
}

module "azure_openai" {
  source = "./modules/azure-openai"

  account_name        = var.account_name
  deployment_name     = var.deployment_name
  deployment_sku      = var.deployment_sku
  capacity            = var.capacity
  location            = azurerm_resource_group.chat_model.location
  model_name          = var.model_name
  model_version       = var.model_version
  resource_group_id   = azurerm_resource_group.chat_model.id
  resource_group_name = azurerm_resource_group.chat_model.name
}
