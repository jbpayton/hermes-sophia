# Patches for Hermes Agent

Small changes to Hermes itself that the continuity companion needs.

## `hermes-plugin-turn-display.patch`

**Why:** a turn a plugin injects (`ctx.inject_message`) is proactive work, like Hermes's own heartbeat. Its tool progress, streaming and "still working" notices would ping you before its result is known, and the plugin decides what of the final reply reaches you; the continuity companion may hold it. Its thoughts are different: you may want to read along. Before this patch, an injected turn showed everything your display settings show. With streaming on, its reply could even reach you before the companion held it.

**What it changes:** an injected turn gets a display policy (`plugin_turn_display` in `gateway/run_turn.py`):

| Surface | Default | |
|---|---|---|
| `thinking` | shown | thinking progress, if your display settings show it |
| `interim` | shown | in-between assistant text (its narration between tool calls) |
| `tool_progress` | hidden | "⚙️ Running …" lines |
| `streaming` | hidden | always keep off while a plugin may hold replies: a streamed reply arrives before it can be held |
| `notices` | hidden | "still working" messages on long turns |

On Telegram's default notification mode ("important"), what is shown arrives silently. Only final replies notify.

Change the defaults in `config.yaml`:

```yaml
display:
  plugin_turns:
    tool_progress: true     # see the tools it uses, too
```

A gateway running in proxy mode (`GATEWAY_PROXY_URL`) gives injected turns the full heartbeat treatment instead: fully quiet, no thoughts shown. That's expected, not a regression (noted by Sophia in review).

A plugin can narrow the policy for one turn (`inject_message(..., display={"interim": False})`), never widen it past your settings. The continuity companion uses this to be fully quiet in quiet hours (or always, with its `show_thoughts: false`). Your own turns, heartbeats, background-process notices and delegation results are unchanged.

**Tested** against Hermes v0.21.4 (`524041b`):
- the patch's own tests (`tests/gateway/test_plugin_turn_display.py`), covering the policy, tool progress following it, and `inject_message` carrying it;
- the related gateway tests for progress, plugin injection, internal-notification markers and silence tokens;
- the wider gateway suite, whose failures are the same as without the patch.

**Apply** (it takes effect when the gateway next restarts):

```bash
cd ~/.hermes/hermes-agent
git apply ~/sophia-hermes-research/hermes-sophia/patches/hermes-plugin-turn-display.patch
```

**Undo:** `git apply -R` with the same file. `hermes update` stashes local changes (`updates.non_interactive_local_changes: stash`), so re-apply after an update if it isn't upstream by then. The companion works on an unpatched Hermes too; its turns then show whatever your display settings show. The change is general rather than specific to Sophia, so it's a candidate for an upstream pull request.
