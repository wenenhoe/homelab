output "ip_address" {
  description = "Static IPv4 address of the VM."
  value       = module.scratch.ip_address
}

output "ssh" {
  description = "The ssh command that reaches the VM from a host that routes to its VLAN."
  value       = "ssh ${var.admin_username}@${module.scratch.ip_address}"
}
