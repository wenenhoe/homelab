output "vm_id" {
  description = "VMID of the VM."
  value       = proxmox_virtual_environment_vm.this.vm_id
}

output "wan_mac_address" {
  description = "MAC address of the WAN NIC."
  value       = "${local.mac_prefix}:00"
}

output "lan_mac_address" {
  description = "MAC address of the LAN NIC."
  value       = "${local.mac_prefix}:01"
}
