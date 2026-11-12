output "endpoint" {
  description = "Azure OpenAI account endpoint."
  value       = azurerm_cognitive_account.model.endpoint
}

output "deployment_name" {
  description = "Azure OpenAI model deployment name."
  value       = azurerm_cognitive_deployment.chat.name
}
