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

variable "node_name" {
  description = "Name of the Proxmox node the VM runs on."
  type        = string
  default     = "pve"
}

variable "vm_id" {
  description = "VMID of the scratch VM. Its hundred picks the VLAN and its last two digits the address, as for every VM of proxmox_ubuntu_vm, which also rejects a VMID outside its range."
  type        = number
}

variable "name" {
  description = "VM name, also its hostname."
  type        = string
  default     = "scratch"
}

variable "template_vm_id" {
  description = "VMID of the Ubuntu template the VM is cloned from: the vm_id of proxmox_ubuntu_template, which the root module builds."
  type        = number
  default     = 106
}

variable "cores" {
  description = "Number of vCPU cores."
  type        = number
  default     = 2
}

variable "memory_mb" {
  description = "Memory in MiB."
  type        = number
  default     = 2048
}

variable "disk_gb" {
  description = "Size of the system disk in GiB, at least the template's 8."
  type        = number
  default     = 16
}

variable "admin_username" {
  description = "Account cloud-init creates and the one that logs in over SSH."
  type        = string
  default     = "scratch"
}

variable "ssh_public_keys" {
  description = "Public keys installed for admin_username."
  type        = list(string)
}

variable "dns_domain" {
  description = "Search domain handed to the VM, the lab's internal zone."
  type        = string
}

variable "dns_servers" {
  description = "Nameservers handed to the VM. Defaults to the VLAN's gateway, .1."
  type        = list(string)
  default     = null
}
