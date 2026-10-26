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

variable "image_path" {
  description = "Local path of the unpacked OPNsense nano image of one release, an amd64 .img file. The caller checks the published .img.bz2 against its checksum file and unpacks it."
  type        = string

  validation {
    condition     = endswith(var.image_path, ".img") && strcontains(basename(var.image_path), "-nano-")
    error_message = "image_path must be the unpacked OPNsense nano .img file."
  }
}

variable "image_datastore_id" {
  description = "Datastore the image and the seed are stored in. It must allow import content."
  type        = string
  default     = "tofu-images"
}

variable "datastore_id" {
  description = "Datastore for the system disk."
  type        = string
  default     = "local-lvm"
}

variable "wan_bridge" {
  description = "Bridge the WAN NIC attaches to: the physical WAN bridge, or the VLAN-aware bridge when wan_vlan_id is set."
  type        = string
  default     = "vmbr0"
}

variable "wan_vlan_id" {
  description = "VLAN tag of the WAN NIC, for a WAN that is a VLAN of the VLAN-aware bridge. Null attaches it untagged."
  type        = number
  default     = null

  validation {
    condition     = var.wan_vlan_id == null || (var.wan_vlan_id >= 1 && var.wan_vlan_id <= 4094)
    error_message = "wan_vlan_id must be null or a VLAN ID from 1 to 4094."
  }
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
  description = "Size of the system disk in GiB. The image is smaller, and the gateway grows its root file system into the disk at the first boot."
  type        = number
  default     = 32
}

variable "seed_image_path" {
  description = "Local path of a raw disk image holding conf/config.xml, attached as a second disk (scsi1) for the importer to read at the first boot. Null attaches none."
  type        = string
  default     = null
}

variable "started" {
  description = "Whether the VM is started when created. The script that answers the importer must be connected to the serial socket before the first boot passes the importer's prompt, so a caller that runs it sets this to false and starts the VM from the script."
  type        = bool
  default     = true
}
