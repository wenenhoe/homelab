variable "proxmox_endpoint" {
  description = "Proxmox VE API URL, for example https://pve.example.lan:8006/."
  type        = string

  validation {
    condition     = startswith(var.proxmox_endpoint, "https://")
    error_message = "proxmox_endpoint must be an https:// URL."
  }
}

variable "proxmox_api_token" {
  description = "Proxmox API token in the form user@realm!tokenid=secret."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^@]+@[^!]+![^=]+=.+$", var.proxmox_api_token))
    error_message = "proxmox_api_token must have the form user@realm!tokenid=secret."
  }
}

variable "proxmox_insecure" {
  description = "Skip TLS verification of the Proxmox API certificate."
  type        = bool
  default     = false
}

variable "proxmox_node" {
  description = "Name of the Proxmox node Tofu provisions on."
  type        = string
  default     = "pve"
}
