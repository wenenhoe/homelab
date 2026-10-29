variable "proxmox_endpoint" {
  description = "Proxmox VE API URL, for example https://pve.example.lan:8006/."
  type        = string
}

variable "proxmox_api_token" {
  description = "Proxmox API token in the form user@realm!tokenid=secret."
  type        = string
  sensitive   = true
}

variable "proxmox_insecure" {
  description = "Skip TLS verification of the Proxmox API certificate."
  type        = bool
  default     = false
}

variable "node_name" {
  description = "Name of the Proxmox node the scratch gateway is built on."
  type        = string
  default     = "pve"
}

variable "vm_id" {
  description = "VMID of the scratch gateway, outside every range the lab uses."
  type        = number
  default     = 501
}

variable "image_volume_id" {
  description = "Import volume that already holds the unpacked image on the node, which scratch_gateway.sh stages. Leave it unset to have Tofu download and upload the image."
  type        = string
  default     = null
}

variable "image_url" {
  description = "The nano image of the pinned release, from the release mirror. Only with image_checksum, when image_volume_id is not set."
  type        = string
  default     = null
}

variable "image_checksum" {
  description = "SHA-256 of image_url, from the release's published checksum file."
  type        = string
  default     = null
}

variable "image_cache_dir" {
  description = "Where the module downloads and unpacks the image when it does."
  type        = string
  default     = ".image-cache"
}

variable "image_datastore_id" {
  description = "Datastore that holds the image and the seed as import content."
  type        = string
  default     = "tofu-images"
}

variable "datastore_id" {
  description = "Datastore for the gateway's system disk."
  type        = string
  default     = "local-lvm"
}

variable "seed_image_path" {
  description = "The seed disk image the seed builder wrote."
  type        = string
}

variable "wan_bridge" {
  description = "Bridge for the WAN NIC. The gateway's DHCP client gets an address and a route out on it."
  type        = string
  default     = "vmbr1"
}

variable "wan_vlan_id" {
  description = "VLAN tag of the WAN NIC when wan_bridge is VLAN-aware and the route out is on a VLAN."
  type        = number
  default     = null
}

variable "lan_bridge" {
  description = "Bridge for the LAN NIC. Must have no ports: the seed's LAN serves DHCP."
  type        = string
  default     = "vmbr9"
}
