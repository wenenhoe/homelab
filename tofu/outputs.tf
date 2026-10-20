# Inventory name => module.<name>.inventory_entry, for every VM Ansible manages.
# tools/tofu_inventory turns this into the generated inventory file.
output "ansible_hosts" {
  description = "Ansible-managed VMs, keyed by inventory host name."
  value       = {}
}
