output "model_base_url" {
  description = "Set FOLIUM_AGENTS_MODEL_BASE_URL to this Azure OpenAI v1 endpoint."
  value       = "${trimsuffix(module.azure_openai.endpoint, "/")}/openai/v1"
}

output "model_name" {
  description = "Set FOLIUM_AGENTS_MODEL_NAME to this Azure deployment name."
  value       = module.azure_openai.deployment_name
}

output "resource_group_name" {
  description = "Resource group created for the model deployment."
  value       = azurerm_resource_group.chat_model.name
}
