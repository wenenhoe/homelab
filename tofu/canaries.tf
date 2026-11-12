# One canary VM per zone, outside every host under test (ADR 0094). The runner in
# tools/network_checks opens an SSH session to a canary and tries the zone's flows from it.
# The VM holds no credential and runs nothing of its own, and it is in no Ansible group,
# so it is not in ansible_hosts. The map is the zones that have one; a zone is added once
# the gateway admits the runner's host to the canary's address on 22 (a VMID's host part
# 08 keeps clear of the DHCP pool, and the address is the zone's canary in
# tools/network_checks/flows.yaml).
locals {
  canary_vm_ids = {
    services = 208
  }
}

module "canary" {
  # No key, no canaries: a canary nobody can log in to shows nothing.
  for_each        = length(var.canary_ssh_public_keys) > 0 ? local.canary_vm_ids : {}
  source          = "./modules/proxmox_ubuntu_vm"
  node_name       = var.proxmox_node
  vm_id           = each.value
  name            = "canary-${each.key}"
  template_vm_id  = module.ubuntu_template.vm_id
  cores           = 1
  memory_mb       = 1024
  disk_gb         = 8
  admin_username  = "canary"
  dns_domain      = var.dns_domain
  ssh_public_keys = var.canary_ssh_public_keys
}
