variable "resource_group_name" {
  description = "Name of the resource group for the Azure model resource."
  type        = string
}

variable "location" {
  description = "Azure region that supports the selected model deployment."
  type        = string
}

variable "account_name" {
  description = "Globally unique Azure AI account name."
  type        = string
}

variable "deployment_name" {
  description = "Azure deployment name; use this as FOLIUM_AGENTS_MODEL_NAME."
  type        = string
}

variable "model_name" {
  description = "Azure OpenAI model name supported in the selected region."
  type        = string
}

variable "model_version" {
  description = "Exact model version supported in the selected region."
  type        = string
}

variable "deployment_sku" {
  description = "Azure OpenAI deployment SKU, such as GlobalStandard."
  type        = string
}

variable "capacity" {
  description = "Azure OpenAI deployment capacity in the selected SKU's units."
  type        = number

  validation {
    condition     = var.capacity > 0
    error_message = "Deployment capacity must be greater than zero."
  }
}
