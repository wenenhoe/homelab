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
