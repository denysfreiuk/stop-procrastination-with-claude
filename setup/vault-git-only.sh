#!/bin/sh
# Forced command for the SSH keys of phones and other devices: with such a key
# they can only pull and push the vault repository, no shell and nothing else.
# setup.py add-device writes the line into ~/.ssh/authorized_keys:
#   command="'/path/vault-git-only.sh' '/path/vault'",restrict ssh-ed25519 AAAA… phone

# The real path of a folder, with symlinks and ".." resolved; works on Linux and macOS.
canonical() { (cd -- "$1" 2>/dev/null && pwd -P); }

vault=$(canonical "$1") || { echo "Vault not found." >&2; exit 1; }
command=${SSH_ORIGINAL_COMMAND%% *}
requested=${SSH_ORIGINAL_COMMAND#* }
requested=${requested#\'}
requested=${requested%\'}

case "$command" in
  git-upload-pack|git-receive-pack) ;;
  *) echo "Only git access to the vault is allowed." >&2; exit 1 ;;
esac
case "$requested" in
  *"'"*|*";"*|*"&"*|*"|"*|*'$'*|*'`'*) echo "Only the vault repository is available." >&2; exit 1 ;;
esac
if [ "$(canonical "$requested")" != "$vault" ]; then
  echo "Only the vault repository is available." >&2
  exit 1
fi
# The path passed on is our own, never the one the client sent.
exec git-shell -c "$command '$vault'"
