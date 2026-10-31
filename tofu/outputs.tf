# Inventory name => module.<name>.inventory_entry, for every VM Ansible manages.
# tools/tofu_inventory turns this into the generated inventory file.
output "ansible_hosts" {
  description = "Ansible-managed VMs, keyed by inventory host name."
  value       = {}
}

output "ubuntu_image_prepare_command" {
  description = "Command that builds the image the template imports; run it on the operator host, then copy the result to the node's import directory."
  value       = "tofu/modules/proxmox_ubuntu_template/prepare_image.sh ${var.ubuntu_image_url} ${var.ubuntu_image_checksum} OUT_DIR"
}
