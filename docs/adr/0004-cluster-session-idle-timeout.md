# A scheduled sample runs in a cluster session

Status: accepted. Supersedes the five-second poll in ADR 0003. On-demand
retrieval is unchanged.

The schedule used to wake every five seconds and pull a mirror that a
resident `collector.sh loop` on the login node was expected to keep full.
That loop is the login-node process the watcher decision refuses to copy,
and the poll does nothing for almost the whole interval.

The schedule still lives in the controller. The thread sleeps until the next
run is due, and a settings change wakes it at once. A due run opens a tmux
session named `unity-hpc` when it is not already there, sends `collector.sh
once`, waits for that sample, then pulls. The shell exports `TMOUT` to one
and a half times the interval, in seconds. A 30 minute schedule closes the
session after 45 minutes with no command. Turning the schedule off sends
nothing, so the same quiet period closes the session.

Scaffold and setup copy the sample scripts only. They do not start `loop`.
Retention of summaries is unchanged: `summaries.db` still keeps every
summary row. ADR 0005 moves the raw archive onto this machine and prunes
the cluster after a successful pull. `once` still runs the 35-day backstop.

A systemd timer beside the controller was rejected. The panel would not see
the session, and the quiet period would belong to a second install. Keeping
the five-second poll and only changing the remote command was rejected. The
poll is not the schedule.
