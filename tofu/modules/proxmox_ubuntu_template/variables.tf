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
  description = "https URL of the Ubuntu cloud image, pinned to a dated release directory so the file never changes under the checksum. Set it with image_checksum to have Proxmox download the image, or leave it unset and give image_volume_id."
  type        = string
  default     = null

  validation {
    condition     = var.image_url == null || (startswith(var.image_url, "https://") && endswith(var.image_url, ".img"))
    error_message = "image_url must be an https:// URL of an Ubuntu cloud .img file."
  }
}

variable "image_checksum" {
  description = "SHA-256 of the image at image_url, as published in the release's SHA256SUMS."
  type        = string
  default     = null

  validation {
    condition     = var.image_checksum == null || can(regex("^[0-9a-f]{64}$", var.image_checksum))
    error_message = "image_checksum must be 64 lowercase hexadecimal characters."
  }
}

variable "image_volume_id" {
  description = "Import volume that already holds the image on the node, as <datastore>:import/<file>.qcow2, such as the copy prepare_image.sh builds. The template's disk is imported from it and nothing is downloaded. Leave image_url and image_checksum unset when it is given."
  type        = string
  default     = null

  validation {
    condition     = var.image_volume_id == null || can(regex("^[^:/]+:import/[^/]+\\.(raw|qcow2|vmdk)$", var.image_volume_id))
    error_message = "image_volume_id must look like tofu-images:import/ubuntu-26.04-server-cloudimg-amd64-release-20260927-no-dyn-netconf.qcow2."
  }
}

variable "image_datastore_id" {
  description = "Datastore the downloaded image is stored in. Its content types must include import, and the token needs Datastore.Allocate on it to replace the image."
  type        = string
  default     = "tofu-images"
}

variable "datastore_id" {
  description = "Datastore for the template's disk and cloud-init drive."
  type        = string
  default     = "local-lvm"
}
