# Running independently of ChatGPT

Installed September 25, 2026 as the macOS user LaunchAgent
`com.brandong.forex-bot`. The service is managed by macOS, not a chat session
or editor terminal. Closing ChatGPT does not stop it.

- Starts when Brandon logs in and restarts if the process exits, with a
  60-second restart throttle.
- Runs the existing project and virtual environment from
  `/Users/brandong/Desktop/forex-bot/forex`.
- Uses `caffeinate -i` to prevent idle system sleep while running. The display
  may sleep. Keep the Mac plugged in and connected to the internet.
- Starts with new entries paused, following the existing startup behavior.
  Monitoring and management of existing bot-owned trades still operate.
- Binds the dashboard to localhost. No public network exposure is added.
- Slack delivery is disabled in this service's environment; notifications are
  stored locally. No credentials were copied into the service definition, and
  `.env` remains the application's credential source.

An explicit **Connect #forex** action can override the launch-time mute for
the current process using the supplied token or webhook. The LaunchAgent
still starts muted on its next restart; reconnect explicitly to resume Slack
delivery. The connection flow may send a startup message and replay its outbox.

## Dashboard action fix

Buttons retain their element reference across asynchronous requests, so they
are re-enabled after success or failure. A persistent status banner shows
progress, connection errors and rescan results without being overwritten by
the four-second data refresh. Requests time out after two minutes with a
warning that server work may still be running; they are not automatically
retried. A page reload loads the corrected JavaScript.

Regression checks: `node tests/dashboard_actions.cjs` exercises 48 mocked
success/failure cases without external side effects. A Python regression test
checks explicit Slack credential handling under a muted service environment.

September 26: Each action now also has a persistent result beside its button.
Connection errors begin with **Failed**, and background work is labeled as
started rather than completed. A Sheets sync request is not treated as proof
of a successful upload. The action tests verify local progress, final results,
and the distinction between queued work and confirmed connections.

This does not keep the bot running while the Mac is shut down, forcibly asleep,
or normally asleep with a laptop lid closed. Logging out stops this user
service; a reboot requires login before it starts again. FileVault may require
an interactive unlock. True operation independent of this Mac requires a
separate always-on host and a controlled single-instance migration.

## Dashboard and controls

Dashboard: <http://127.0.0.1:8765>

Health: <http://127.0.0.1:8765/api/health>

The dashboard pause control pauses new entries; it does not shut down the
service. Every process restart resets entries to paused. The service does not
pass `--trade` or automatically re-arm after a crash.

Status:

```bash
launchctl print gui/501/com.brandong.forex-bot
curl --max-time 5 http://127.0.0.1:8765/api/health
```

Stop and unload for the current login session:

```bash
launchctl bootout gui/501/com.brandong.forex-bot
```

Start again:

```bash
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.brandong.forex-bot.plist
```

Restart an already-loaded service after reviewing account state:

```bash
launchctl kickstart -k gui/501/com.brandong.forex-bot
```

To disable future login starts as well, unload it, then move its plist out of
`~/Library/LaunchAgents`. Do not start another terminal copy while this service
owns the bot. The account instance lock adds protection against duplicate
updated instances, but cannot coordinate another computer or legacy runner.

## Files and troubleshooting

Installed definition:
`/Users/brandong/Library/LaunchAgents/com.brandong.forex-bot.plist`

Project copy: [service definition](../service/com.brandong.forex-bot.plist).

Application logs are in `logs/bot.log`, with existing size rotation and
retention. Launch output is in `logs/service.stdout.log` and
`logs/service.stderr.log`; these launch output files do not rotate automatically
and should be monitored for growth. Startup performs network fetches and can
take time before the dashboard begins listening. An HTTP health response
confirms the app is serving, not that every external data provider is healthy.

Some secondary websites may block automated fetches. Inspect application
warnings and calendar freshness before enabling new trades. Credentials and
account details can appear in local logs; do not publish them.

Follow [the reliability guide](RELIABILITY_UPGRADE_2026-09-22.md) for uncertain
broker outcomes and startup reconciliation. Keep `data/`, its database,
order-intent reservations and uncertainty latches intact across restarts.

## Deferred startup tasks (September 29)

The initial full scan, briefing catch-up, Sheets dispatch, tape pulse, intelligence
refresh, and history dispatch now run as one scheduled startup job instead of
blocking dashboard launch. Core initialization still completes first: account
inspection, bar loading, journal preparation and growth accounting. This is not
a guarantee of instantaneous startup when those core broker requests are slow.

`/api/health` includes `startup_tasks` with `pending`, `running`, `complete`, or
`degraded` state, the current task, and completed/failed task names. A task failure
does not prevent subsequent tasks. For Sheets/history, completion here means the
background dispatch returned, not that a remote upload or history study finished;
the existing integration status remains authoritative for those outcomes.

Regression checks verify that dashboard launch does not call or wait for the
initial scan and that failures do not suppress later startup tasks. Validation:
312 Python tests and 48 dashboard action checks passed.

Deployment: activated September 29 after the operator requested implementation.
New entries were paused before the managed service reload. Verified the practice
service returned `ok:true`, `warm:true`, `trading:false`, and the new
`startup_tasks` payload. The dashboard responded while the intelligence task was
still running, confirming optional enrichment no longer blocks its availability.
The initial scan, desk-note task, Sheets dispatch and tape task had returned with
no reported failures at verification. Entries remain paused until explicitly resumed.
