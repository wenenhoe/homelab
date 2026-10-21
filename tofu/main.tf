# With no resources, plan would succeed without contacting Proxmox. Reading
# the node makes it fail on a wrong endpoint, token or node name.
data "proxmox_virtual_environment_node" "pve" {
  node_name = var.proxmox_node
}

module "ubuntu_template" {
  source         = "./modules/proxmox_ubuntu_template"
  node_name      = var.proxmox_node
  image_url      = var.ubuntu_image_url
  image_checksum = var.ubuntu_image_checksum
}

# The isolated 5XX block. The WAN NIC is a client of the current OPNsense's
# LAN on VLAN 20, so the block reaches the internet and `storage` without
# any change to production routing.
module "opnsense_5xx" {
  source       = "./modules/proxmox_opnsense_vm"
  node_name    = var.proxmox_node
  vm_id        = 501
  wan_bridge   = "vmbr1"
  wan_vlan_id  = 20
  iso_url      = var.opnsense_iso_url
  iso_checksum = var.opnsense_iso_checksum
}

module "ubuntu_5xx" {
  source          = "./modules/proxmox_ubuntu_vm"
  node_name       = var.proxmox_node
  vm_id           = 502
  name            = "scratch-502"
  template_vm_id  = module.ubuntu_template.vm_id
  admin_username  = "scratchadmin"
  dns_domain      = var.dns_domain
  ssh_public_keys = var.ssh_public_keys
  tags            = ["5xx"]
}
