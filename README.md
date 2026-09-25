# Listing watcher

Checks a rental listings page every 15 minutes and sends a push notification
(via ntfy) when a new home appears or one becomes available again.

Repository secrets required:
- `WATCH_URL`: the listings page to watch
- `NTFY_TOPIC`: the ntfy topic to send notifications to

Run it manually from the Actions tab. Tick "Send test notification" to check
that notifications arrive.
