variable "node_name" {
  description = "Name of the Proxmox node the VM runs on."
  type        = string
}

variable "vm_id" {
  description = "VMID, which fixes the VLAN, IP address and MAC address. Ranges 2XX to 5XX in blocks of 50, host part 02 to 49: 00 is reserved and 01 is the gateway."
  type        = number

  validation {
    condition     = var.vm_id >= 202 && var.vm_id < 600 && var.vm_id % 50 >= 2
    error_message = "vm_id must be 2XX to 5XX and not the reserved or gateway VMID of a block of 50 (X00, X01, X50, X51)."
  }
}

variable "name" {
  description = "VM name, also its hostname."
  type        = string
}

variable "template_vm_id" {
  description = "VMID of the template to clone, from proxmox_ubuntu_template."
  type        = number
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
  description = "Size of the system disk in GiB. The template's disk is 8, and a clone's disk can only grow."
  type        = number
  default     = 32

  validation {
    condition     = var.disk_gb >= 8
    error_message = "disk_gb must be at least 8, the size of the template's disk."
  }
}

variable "admin_username" {
  description = "Account cloud-init creates, the one Ansible connects as."
  type        = string
}

variable "ssh_public_keys" {
  description = "Public keys installed for admin_username."
  type        = list(string)

  validation {
    condition     = length(var.ssh_public_keys) > 0
    error_message = "ssh_public_keys must hold at least one key, or nothing can log in."
  }
}

variable "dns_domain" {
  description = "Search domain handed to the VM, the lab's internal zone. Required because Proxmox otherwise copies the node's own search domain into every VM."
  type        = string

  validation {
    condition     = length(var.dns_domain) > 0
    error_message = "dns_domain must not be empty, or Proxmox falls back to the node's search domain."
  }
}

variable "dns_servers" {
  description = "Nameservers handed to the VM. Defaults to the VLAN's gateway, .1."
  type        = list(string)
  default     = null
}

variable "lan_bridge" {
  description = "VLAN-aware bridge the NIC attaches to."
  type        = string
  default     = "vmbr1"
}

variable "datastore_id" {
  description = "Datastore for the system disk and cloud-init drive."
  type        = string
  default     = "local-lvm"
}

variable "tags" {
  description = "Tags added to the fixed tofu and ubuntu ones."
  type        = list(string)
  default     = []
}
