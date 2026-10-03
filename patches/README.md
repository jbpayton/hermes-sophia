# Patches for Hermes Agent

Small changes to Hermes itself that the continuity companion needs. Nothing here is applied automatically.

## `hermes-quiet-plugin-turns.patch`

**Why:** Hermes keeps a scheduled heartbeat quiet until its result is known: no tool progress, in-between text, thinking, streaming, typing indicator or "still working" notices. A turn a plugin injects (`ctx.inject_message`) didn't get the same treatment. So when the continuity companion holds one of its own replies (outreach off, or quiet hours), the tool chatter from that turn could still reach you on Telegram.

**What it changes:** one helper, `quiet_proactive_turn(event)` in `gateway/run_turn.py`. A plugin-injected turn is now treated like a heartbeat for display. Other internal events (background-process notices, delegation results) are unchanged, and so are your own turns. It includes a test, `tests/gateway/test_quiet_plugin_turns.py`.

**Tested** against Hermes v0.21.4 (`524041b`): the new test plus the gateway tests for progress, plugin injection, internal-notification markers and silence tokens.

**Apply**, then restart the gateway:

```bash
cd ~/.hermes/hermes-agent
git apply ~/sophia-hermes-research/hermes-sophia/patches/hermes-quiet-plugin-turns.patch
```

**Undo:** `git apply -R` with the same file. `hermes update` stashes local changes (`updates.non_interactive_local_changes: stash`), so re-apply after an update if it isn't upstream by then. It's general rather than specific to Sophia, so it's a candidate for an upstream pull request.
