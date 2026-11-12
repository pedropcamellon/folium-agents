variable "account_name" {
  description = "Globally unique Azure AI account name."
  type        = string
}

variable "deployment_name" {
  description = "Name of the Azure OpenAI model deployment."
  type        = string
}

variable "deployment_sku" {
  description = "Azure OpenAI deployment SKU."
  type        = string
}

variable "capacity" {
  description = "Azure OpenAI deployment capacity."
  type        = number
}

variable "location" {
  description = "Azure region for the Azure AI account."
  type        = string
}

variable "model_name" {
  description = "Azure OpenAI model name."
  type        = string
}

variable "model_version" {
  description = "Azure OpenAI model version."
  type        = string
}

variable "resource_group_id" {
  description = "Resource group ID for the Azure AI account."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group name for the Azure AI account."
  type        = string
}
