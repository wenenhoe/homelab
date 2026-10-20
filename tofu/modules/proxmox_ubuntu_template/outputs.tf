output "vm_id" {
  description = "VMID of the template, for the clone source of proxmox_ubuntu_vm."
  value       = proxmox_virtual_environment_vm.template.vm_id
}
