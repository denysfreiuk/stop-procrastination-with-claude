#!/bin/sh
# Forced command for the SSH keys of phones and other devices: with such a key
# they can only pull and push the vault repository, no shell and nothing else.
# setup.py add-device writes the line into ~/.ssh/authorized_keys:
#   command="/path/vault-git-only.sh /path/vault",restrict ssh-ed25519 AAAA… phone

vault=$(realpath -e -- "$1" 2>/dev/null) || { echo "Vault not found." >&2; exit 1; }
command=${SSH_ORIGINAL_COMMAND%% *}
requested=${SSH_ORIGINAL_COMMAND#* }
requested=${requested#\'}
requested=${requested%\'}
requested=${requested%/}

case "$command" in
  git-upload-pack|git-receive-pack) ;;
  *) echo "Only git access to the vault is allowed." >&2; exit 1 ;;
esac
if [ "$(realpath -e -- "$requested" 2>/dev/null)" != "$vault" ]; then
  echo "Only the vault repository is available." >&2
  exit 1
fi
# The path passed on is our own, never the one the client sent.
exec git-shell -c "$command '$vault'"
