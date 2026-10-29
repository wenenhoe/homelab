module "opnsense" {
  source = "../../modules/proxmox_opnsense_vm"

  node_name          = var.node_name
  vm_id              = var.vm_id
  name               = "opn-scratch"
  image_url          = var.image_url
  image_checksum     = var.image_checksum
  image_cache_dir    = var.image_cache_dir
  image_datastore_id = var.image_datastore_id
  datastore_id       = var.datastore_id
  seed_image_path    = var.seed_image_path
  wan_bridge         = var.wan_bridge
  wan_vlan_id        = var.wan_vlan_id
  lan_bridge         = var.lan_bridge
  started            = false
}
