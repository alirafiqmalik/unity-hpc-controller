# SSH access without repeated key prompts

Unity accepts an enrolled public key. The matching private key stays on the
controller machine. Its passphrase unlocks that key into an SSH agent; the
passphrase is not sent to Unity. The controller uses the system OpenSSH client
for cluster commands and rsync.

## One-time setup on the controller machine

1. Confirm that `ssh -G unity` lists the expected `hostname`, `user`, and
   `identityfile`. Unity must have that key's public half enrolled.
2. Run `python3 scripts/hpc-ssh-auth-setup --dry-run`, then run the command
   without `--dry-run`. It enables the user-level `ssh-agent.socket` and gives
   the exact `Host unity` block a stable `IdentityAgent` path. It also turns
   off agent forwarding for this host and adds connection and keepalive limits.
   The setup never reads the private key or its passphrase.
3. In the controller's **Settings → Config**, select **Unlock key** and enter
   the private key passphrase once. The controller loads the key into the
   shared agent. If the desktop Secret Service is available, it saves the
   passphrase in that machine's encrypted desktop keyring and says so in the
   result. Select **Test** to check the full SSH login.

The panel reports when the desktop keyring is locked or unavailable. Unlock
that keyring in the desktop session before using **Unlock key** if you want
the passphrase saved across agent restarts. With automatic desktop login,
the login keyring may stay locked after a reboot; a normal password login or
an explicit keyring unlock is then required before unattended restoration.

The saved keyring item is indexed by the public key fingerprint. The key file
remains passphrase-protected. The passphrase is never put in `.env`, SSH config,
Git, logs, command arguments, or the controller settings file. An unattended
controller can restore it into an empty agent after a restart **when the
desktop keyring is unlocked**. A controller started before desktop login may
have to wait for that login. A locked or unavailable keyring is reported as an
unlock needed; it is not silently bypassed.

The panel's **Unlock key** action is also available without this setup, but
then it may use whichever agent socket the controller inherited. A controller
restart can lose access if that socket disappears. On Linux installations
without systemd user services or Secret Service, use the platform's own SSH
agent and keychain integration and verify that controller processes see the
same agent socket.

## If access fails

Run `ssh -G unity` to inspect the effective alias. Run `ssh-add -l` with the
alias's `IdentityAgent` socket to check for a loaded signer. Use the panel's
**Test** action; it uses batch mode and a connection deadline, so a background
request cannot wait for an invisible passphrase prompt. If the public key is
offered and the server says `Server accepts key`, but login still fails, unlock
the private key. If the server rejects the public key, check account enrollment
and Unity's access policy. If a connection stalls, check network reachability;
keepalives address dropped connections, not authentication failures.

No local cache guarantees access forever. The cluster can revoke a key or
account, and a hardware FIDO key may require presence or touch on every use.
The [source comparison](research/ssh-authentication-comparison.md) gives the
OpenSSH, Unity, T3 Code, and desktop keyring references.
