variable "node_name" {
  description = "Name of the Proxmox node the VM runs on."
  type        = string
}

variable "vm_id" {
  description = "VMID, which fixes the NIC MAC addresses. OPNsense takes the gateway VMID of its range, host part 01."
  type        = number
  default     = 201

  validation {
    condition     = var.vm_id >= 201 && var.vm_id < 600 && var.vm_id % 100 == 1
    error_message = "vm_id must be the 01 VMID of a 2XX to 5XX range."
  }
}

variable "name" {
  description = "VM name."
  type        = string
  default     = "OPNsense"
}

variable "iso_url" {
  description = "https URL of the OPNsense installer image, the dvd amd64 .iso.bz2 of one release."
  type        = string

  validation {
    condition     = startswith(var.iso_url, "https://") && endswith(var.iso_url, ".iso.bz2")
    error_message = "iso_url must be an https:// URL of an OPNsense .iso.bz2 file."
  }
}

variable "iso_checksum" {
  description = "SHA-256 of the file at iso_url, as OPNsense publishes it."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.iso_checksum))
    error_message = "iso_checksum must be 64 lowercase hexadecimal characters."
  }
}

variable "iso_datastore_id" {
  description = "Datastore the installer image is stored in."
  type        = string
  default     = "local"
}

variable "datastore_id" {
  description = "Datastore for the system disk."
  type        = string
  default     = "local-lvm"
}

variable "wan_bridge" {
  description = "Physical WAN bridge, attached untagged."
  type        = string
  default     = "vmbr0"
}

variable "lan_bridge" {
  description = "VLAN-aware bridge every other VM attaches to, attached untagged so OPNsense sees every VLAN."
  type        = string
  default     = "vmbr1"
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
  description = "Size of the system disk in GiB."
  type        = number
  default     = 32
}
