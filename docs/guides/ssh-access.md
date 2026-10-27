# SSH access for the headless controller

The controller uses the system OpenSSH client and the backend's `ssh_host` and
`ssh_identity`. Enroll your public key with Unity and keep its private half on
the controller machine.

From the repository root, inspect the alias and the optional Linux agent setup:

```bash
ssh -G unity
python3 scripts/hpc-ssh-auth-setup --dry-run
```

Review that output before applying the setup without `--dry-run`. The helper
configures a stable user-level agent socket and connection limits. Load the
identity into the agent visible to the controller using your platform's
`ssh-add` workflow. A systemd service must see the same agent socket; a loaded
identity in another shell does not establish that the service can use it.

Check noninteractive access from the controller machine:

```bash
timeout 20 ssh -o BatchMode=yes -o ConnectTimeout=10 unity true
scripts/hpc-campaign probe
```

Use the backend's actual alias and identity. A successful SSH connection checks
access; a successful catalog refresh also checks the Slurm queries needed for
planning. Scheduled operations cannot answer an interactive passphrase prompt.

If access fails, inspect the effective `IdentityAgent`, identity file, enrolled
public key, and network route. Keep passphrases out of shell arguments and
configuration files. Use the operating system's agent or keychain integration
for unattended access.

Continue with [backend configuration](../backend-campaigns.md#start-and-configure).
The [SSH comparison](../research/ssh-authentication-comparison.md) and
[historical reliability assessment](../research/ssh-connection-reliability.md)
record the supporting research.
