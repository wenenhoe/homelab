output "vm_id" {
  description = "VMID of the VM."
  value       = proxmox_virtual_environment_vm.this.vm_id
}

output "hostname" {
  description = "Name of the VM."
  value       = proxmox_virtual_environment_vm.this.name
}

output "datastore_id" {
  description = "Datastore of the VM's system disk."
  value       = proxmox_virtual_environment_vm.this.disk[0].datastore_id
}

output "ip_address" {
  description = "Static IPv4 address, without the prefix length."
  value       = local.ip_address
}

output "mac_address" {
  description = "MAC address of the NIC."
  value       = local.mac_address
}

output "inventory_entry" {
  description = "What the Ansible inventory generator reads for this VM."
  value = {
    ip_address     = local.ip_address
    admin_username = var.admin_username
  }
}
