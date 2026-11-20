# The production gateway, VMID 201. The root module builds it from the module the scratch gateway
# uses, with the values of the hand-built VM it replaces, except its NICs: they carry the MACs the
# MAC scheme derives from VMID 201. started = false: the VM is created stopped, and first_boot.sh
# starts it and answers the importer. A later apply never starts or stops it. docs/topics/infra/tofu/opnsense-vm.md#the-production-gateway says how it is
# built and what to check first.

variable "opnsense_image_volume_id" {
  description = "Import volume that holds the unpacked OPNsense image on the node. The scratch gateway's stage_image.sh writes it from the pinned release in tofu/scratch/opnsense/image-pin.yaml, under the name the release's file gives."
  type        = string
  default     = "tofu-images:import/OPNsense-26.1.6-nano-amd64.raw"
}

variable "opnsense_seed_image_path" {
  description = "Local path of the seed disk that build_seed.sh wrote, for the gateway's first boot. Null attaches none: unset it and apply once the first boot is done, which drops the uploaded file."
  type        = string
  default     = null
}

module "opnsense" {
  source             = "./modules/proxmox_opnsense_vm"
  node_name          = var.proxmox_node
  vm_id              = 201
  name               = "OPNsense"
  image_volume_id    = var.opnsense_image_volume_id
  image_datastore_id = var.image_datastore_id
  datastore_id       = "local-lvm"
  seed_image_path    = var.opnsense_seed_image_path
  wan_bridge         = "vmbr0"
  lan_bridge         = "vmbr1"
  startup_order      = 1
  started            = false
}
