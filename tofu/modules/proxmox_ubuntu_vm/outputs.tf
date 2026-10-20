output "vm_id" {
  description = "VMID of the VM."
  value       = proxmox_virtual_environment_vm.this.vm_id
}

output "hostname" {
  description = "Name of the VM."
  value       = proxmox_virtual_environment_vm.this.name
}

output "ip_address" {
  description = "Static IPv4 address, without the prefix length."
  value       = local.ip_address
}

output "mac_address" {
  description = "MAC address of the NIC."
  value       = local.mac_address
}
