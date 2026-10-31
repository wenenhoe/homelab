output "vm_id" {
  description = "VMID of the template, for the clone source of proxmox_ubuntu_vm."
  value       = proxmox_virtual_environment_vm.template.vm_id
}

output "image_volume_id" {
  description = "Import volume the template's disk is imported from."
  value       = local.image_volume
}
