locals {
  # prepare_image.sh names its output after the pinned file, its release directory and the
  # timezone, so a new pin or another zone selects a new volume and the template is replaced.
  ubuntu_image_volume_id = "${var.image_datastore_id}:import/${trimsuffix(basename(var.ubuntu_image_url), ".img")}-${basename(dirname(var.ubuntu_image_url))}-prepared-${replace(var.timezone, "/", "-")}.qcow2"
}

# With no resources, plan would succeed without contacting Proxmox. Reading
# the node makes it fail on a wrong endpoint, token or node name.
data "proxmox_virtual_environment_node" "pve" {
  node_name = var.proxmox_node
}

module "ubuntu_template" {
  source          = "./modules/proxmox_ubuntu_template"
  node_name       = var.proxmox_node
  image_volume_id = local.ubuntu_image_volume_id
}

module "play" {
  source          = "./modules/proxmox_ubuntu_vm"
  node_name       = var.proxmox_node
  vm_id           = 204
  name            = "play"
  template_vm_id  = module.ubuntu_template.vm_id
  cores           = 4
  memory_mb       = 4096
  disk_gb         = 64
  admin_username  = "playadmin"
  dns_domain      = var.dns_domain
  ssh_public_keys = var.ansible_ssh_public_keys
}

module "security" {
  source          = "./modules/proxmox_ubuntu_vm"
  node_name       = var.proxmox_node
  vm_id           = 205
  name            = "security"
  template_vm_id  = module.ubuntu_template.vm_id
  cores           = 4
  memory_mb       = 2048
  disk_gb         = 64
  admin_username  = "secadmin"
  dns_domain      = var.dns_domain
  ssh_public_keys = var.ansible_ssh_public_keys
}

module "storage" {
  source          = "./modules/proxmox_ubuntu_vm"
  node_name       = var.proxmox_node
  vm_id           = 206
  name            = "storage"
  template_vm_id  = module.ubuntu_template.vm_id
  cores           = 4
  memory_mb       = 4096
  disk_gb         = 128
  datastore_id    = "backup"
  admin_username  = "storeadmin"
  dns_domain      = var.dns_domain
  ssh_public_keys = var.ansible_ssh_public_keys
}

module "services" {
  source          = "./modules/proxmox_ubuntu_vm"
  node_name       = var.proxmox_node
  vm_id           = 203
  name            = "services"
  template_vm_id  = module.ubuntu_template.vm_id
  cores           = 4
  memory_mb       = 2048
  disk_gb         = 64
  admin_username  = "svcadmin"
  dns_domain      = var.dns_domain
  ssh_public_keys = var.ansible_ssh_public_keys
}

module "tailscale" {
  source          = "./modules/proxmox_ubuntu_vm"
  node_name       = var.proxmox_node
  vm_id           = 202
  name            = "tailscale"
  template_vm_id  = module.ubuntu_template.vm_id
  cores           = 2
  memory_mb       = 2048
  disk_gb         = 16
  admin_username  = "tsadmin"
  dns_domain      = var.dns_domain
  ssh_public_keys = var.ansible_ssh_public_keys
}
