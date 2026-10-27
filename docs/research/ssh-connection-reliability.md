# SSH connection reliability in developer apps

> Historical assessment from 2026-10-02. References to UI actions describe the
> earlier implementation. Use the [current SSH guide](../guides/ssh-access.md)
> for the headless controller.

Researched 2026-10-02. This note uses the upstream T3 Code source at
[`8bc40b4`](https://github.com/pingdotgg/t3code/tree/8bc40b4e07bb7b4b0f71876d59520360c9bf958c),
Microsoft's Remote-SSH documentation, the OpenSSH manuals, and the rsync manual.
T3 Code and VS Code run long-lived remote development servers; Unity HPC
retrieval uses short SSH commands and rsync. Their lifecycle ideas transfer,
but a persistent tunnel is not required for this controller.

## What the apps do

| Pattern | Primary-source evidence | Relevance here |
| --- | --- | --- |
| Use the user's SSH host alias and inspect its effective settings. | T3 Code resolves an alias with [`ssh -G`](https://github.com/pingdotgg/t3code/blob/8bc40b4e07bb7b4b0f71876d59520360c9bf958c/packages/ssh/src/command.ts); OpenSSH says `-G` evaluates `Host` and `Match` blocks ([ssh(1)](https://man.openbsd.org/ssh.1)). VS Code asks users to verify the same host with terminal SSH first ([Remote-SSH](https://code.visualstudio.com/docs/remote/ssh)). | Keep one saved alias for all controller-originated cluster operations. Show effective host, user, port, identity, and agent socket in diagnostics without exposing secrets. |
| Make prompts an explicit mode. | T3 Code uses `BatchMode=yes` when its in-app password prompt is available, retries authentication failures through that prompt, and limits prompt attempts ([auth flow](https://github.com/pingdotgg/t3code/blob/8bc40b4e07bb7b4b0f71876d59520360c9bf958c/packages/ssh/src/tunnel.ts#L1421-L1477)). OpenSSH documents that `BatchMode=yes` disables interactive prompts ([ssh_config(5)](https://man.openbsd.org/ssh_config.5)). | Scheduled pulls need a fail-fast, non-interactive path. Unlocking the key in the controller is a separate interactive action. Do not wait for an invisible passphrase prompt in a background job. |
| Bound every stage and report the stage that failed. | T3 Code bounds individual SSH commands and logs timeout/failure ([command runner](https://github.com/pingdotgg/t3code/blob/8bc40b4e07bb7b4b0f71876d59520360c9bf958c/packages/ssh/src/command.ts)); its tunnel has connection liveness settings and races readiness against process exit ([tunnel](https://github.com/pingdotgg/t3code/blob/8bc40b4e07bb7b4b0f71876d59520360c9bf958c/packages/ssh/src/tunnel.ts#L1137-L1319)). VS Code exposes its exact SSH command and full connection log for troubleshooting ([Remote-SSH troubleshooting](https://github.com/microsoft/vscode-remote-release/wiki/Remote-SSH-troubleshooting)). | Record whether failure occurred in SSH sample, rsync dry-run, transfer, rollup, or prune. Preserve the exact safe command and exit status for reproduction. Add connection, inactivity, and total deadlines to unattended transfers. |
| Check a cached connection before reuse; serialize its lifecycle. | T3 Code checks HTTP readiness before reusing a tunnel, closes stale tunnels, and uses a lock per target so reconnect cannot race disconnect ([manager](https://github.com/pingdotgg/t3code/blob/8bc40b4e07bb7b4b0f71876d59520360c9bf958c/packages/ssh/src/tunnel.ts#L1330-L1345), [reuse](https://github.com/pingdotgg/t3code/blob/8bc40b4e07bb7b4b0f71876d59520360c9bf958c/packages/ssh/src/tunnel.ts#L1603-L1646)). | The controller already serializes retrieval with a local lock. Keep the probe and real pull under that lock and make the same connection settings apply to both. A permanent SSH tunnel would add process state without helping an rsync pull. |
| Keep remote process ownership separate from access. | T3 Code stops a remote server on disconnect only when it launched that server ([remote architecture](https://github.com/pingdotgg/t3code/blob/8bc40b4e07bb7b4b0f71876d59520360c9bf958c/docs/internals/remote.md), [user guide](https://github.com/pingdotgg/t3code/blob/8bc40b4e07bb7b4b0f71876d59520360c9bf958c/docs/user/remote-access.md)). | The controller may own its `unity-hpc` tmux session. It should not assume ownership of unrelated cluster sessions or scripts. |

## Assessment for this controller

1. **P0 — Make sampling and retrieval share the same authentication route.**
   `controller/cluster_session.py` runs the sample through the saved
   `ssh_host`/`ssh_identity`. `cluster-intel/sync-telemetry.sh` instead passes
   `UNITY_TELEMETRY_SRC` to rsync; rsync chooses its SSH transport and uses the
   host before the colon ([rsync(1)](https://download.samba.org/pub/rsync/rsync.1)).
   The saved identity is not explicitly passed to that transport. A successful
   panel SSH probe therefore does not prove that the dry-run or real pull can
   authenticate. Route the pull through the configured alias and identity,
   preserving the remote path, then test both operations using the same
   controller process environment. Rsync's `--rsh` option can name the remote
   shell; `--timeout` covers stalled I/O, while `--contimeout` applies to an
   rsync daemon connection, not the single-colon SSH path
   ([rsync(1)](https://download.samba.org/pub/rsync/rsync.1)).

2. **P0 — Diagnose the agent that the controller actually uses.**
   `unlock_identity()` can start an agent and change `SSH_AUTH_SOCK` inside the
   controller process. OpenSSH identifies an agent by this socket, and
   `ssh-add` requires the same socket to inspect its keys
   ([ssh-agent(1)](https://man.openbsd.org/ssh-agent.1),
   [ssh-add(1)](https://man.openbsd.org/ssh-add.1)). A separate shell's empty
   agent does not disprove an unlocked controller agent. Verify with the
   controller's status/probe endpoints or a child launched by that process.
   When debugging, compare socket paths and key fingerprints, not passphrases.
   Check the effective `IdentityAgent` setting too: OpenSSH says it overrides
   `SSH_AUTH_SOCK` ([ssh_config(5)](https://man.openbsd.org/ssh_config.5)).

3. **P1 — Bound and classify unattended connection failures.**
   Use an SSH connection deadline and server-alive settings for operations
   that can stall. Keep the existing total timeout, and add rsync I/O timeout
   so a silent transfer reports a specific failure before the one-hour job
   budget expires. Surface authentication, host-key, route, missing remote
   command, and stalled-transfer failures separately where SSH/rsync output
   permits. OpenSSH documents `ConnectTimeout`, `ServerAliveInterval`, and
   `ServerAliveCountMax` ([ssh_config(5)](https://man.openbsd.org/ssh_config.5)).
   Command-line `-o` values take priority over the matching `~/.ssh/config`
   directives; they do **not** bypass the entire SSH config file. Choose
   defaults with that override in mind.

4. **P2 — Treat remote collector updates as a separate deployment policy.**
   The retired setup runbook required an explicit
   opt-in before copying scripts to the shared login node. Automatic updates
   are outside the retrieval authentication failure. If deployment is later
   authorized, use the controller's saved alias and identity, compare a local
   and remote version/hash, write to a temporary remote path, and replace only
   after verification. This follows the same ownership separation used by
   T3 Code; it needs its own consent, rollback, and concurrency design.

The comments in `controller/cluster_session.py` that say `BatchMode` and
`ConnectTimeout` “bypass ~/.ssh/config” should be corrected: OpenSSH documents
per-directive precedence, with command-line settings ahead of user config
([ssh_config(5)](https://man.openbsd.org/ssh_config.5)).
