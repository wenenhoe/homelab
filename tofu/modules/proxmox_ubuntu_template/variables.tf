variable "node_name" {
  description = "Name of the Proxmox node the template is built on."
  type        = string
}

variable "vm_id" {
  description = "VMID of the template, in the 1XX templates range."
  type        = number
  default     = 106

  validation {
    condition     = var.vm_id > 100 && var.vm_id < 200
    error_message = "vm_id must be in the 1XX templates range, above the reserved 100."
  }
}

variable "name" {
  description = "Name of the template VM."
  type        = string
  default     = "ubuntu-cloudinit"
}

variable "image_url" {
  description = "https URL of the Ubuntu cloud image, pinned to a dated release directory so the file never changes under the checksum."
  type        = string

  validation {
    condition     = startswith(var.image_url, "https://") && endswith(var.image_url, ".img")
    error_message = "image_url must be an https:// URL of an Ubuntu cloud .img file."
  }
}

variable "image_checksum" {
  description = "SHA-256 of the image at image_url, as published in the release's SHA256SUMS."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.image_checksum))
    error_message = "image_checksum must be 64 lowercase hexadecimal characters."
  }
}

variable "image_datastore_id" {
  description = "Datastore the downloaded image is stored in. Its content types must include import."
  type        = string
  default     = "local"
}

variable "datastore_id" {
  description = "Datastore for the template's disk and cloud-init drive."
  type        = string
  default     = "local-lvm"
}
