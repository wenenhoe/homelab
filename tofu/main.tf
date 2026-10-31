locals {
  # prepare_image.sh names its output after the pinned file and its release directory,
  # so a new pin selects a new volume and the template is replaced.
  ubuntu_image_volume_id = "${var.image_datastore_id}:import/${trimsuffix(basename(var.ubuntu_image_url), ".img")}-${basename(dirname(var.ubuntu_image_url))}-no-dyn-netconf.qcow2"
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
