resource "azurerm_cognitive_account" "model" {
  name                  = var.account_name
  location              = var.location
  resource_group_name   = var.resource_group_name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = var.account_name

  tags = {
    purpose = "folium-agents-chat-model"
  }
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.deployment_name
  cognitive_account_id = azurerm_cognitive_account.model.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = var.deployment_sku
    capacity = var.capacity
  }

  version_upgrade_option = "NoAutoUpgrade"
}
