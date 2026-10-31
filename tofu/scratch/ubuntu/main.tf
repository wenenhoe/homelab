module "scratch" {
  source = "../../modules/proxmox_ubuntu_vm"

  node_name       = var.node_name
  vm_id           = var.vm_id
  name            = var.name
  template_vm_id  = var.template_vm_id
  cores           = var.cores
  memory_mb       = var.memory_mb
  disk_gb         = var.disk_gb
  admin_username  = var.admin_username
  ssh_public_keys = var.ssh_public_keys
  dns_domain      = var.dns_domain
  dns_servers     = var.dns_servers
  tags            = ["scratch"]
}
