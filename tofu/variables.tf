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

variable "ubuntu_image_url" {
  description = "Ubuntu cloud image the template is built from, pinned to a dated release directory. prepare_image.sh turns it into the copy staged on the node."
  type        = string
  default     = "https://cloud-images.ubuntu.com/releases/26.04/release-20260927/ubuntu-26.04-server-cloudimg-amd64.img"

  validation {
    condition     = can(regex("^https://[A-Za-z0-9._~:/%+-]+/[^/]+/[^/]+\\.img$", var.ubuntu_image_url))
    error_message = "ubuntu_image_url must be an https:// URL of an Ubuntu cloud .img file inside a release directory."
  }
}

variable "ubuntu_image_checksum" {
  description = "SHA-256 of ubuntu_image_url, from that release's SHA256SUMS. prepare_image.sh verifies the download against it."
  type        = string
  default     = "8800651811af9a85465ad1d552add729947bb16488dddb4a9b5305a3d97332b2"

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.ubuntu_image_checksum))
    error_message = "ubuntu_image_checksum must be 64 lowercase hexadecimal characters."
  }
}

variable "image_datastore_id" {
  description = "Datastore that holds the prepared image. Its content types must include import."
  type        = string
  default     = "tofu-images"
}

variable "timezone" {
  description = "Timezone of every VM, baked into the prepared image. The same zone as server_timezone in the Ansible inventory, which the containers take as TZ."
  type        = string
  default     = "Asia/Singapore"

  validation {
    condition     = can(regex("^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$", var.timezone))
    error_message = "timezone must be a zoneinfo name such as Asia/Singapore."
  }
}

variable "dns_domain" {
  description = "The lab's internal zone, host_domain in the Ansible inventory. Every VM gets it as its search domain."
  type        = string
}

variable "ansible_ssh_public_keys" {
  description = "Public keys installed for each VM's admin user: the public half of the key Ansible connects with."
  type        = list(string)
}

variable "canary_ssh_public_keys" {
  description = "Public keys installed for each canary VM's user: the public half of the key the boundary-check runner connects with, which is not the key Ansible uses. Empty builds no canary."
  type        = list(string)
  default     = []
}
