# The Sophia tab

Sophia adds a tab to the Hermes dashboard for watching her memory, correcting it and configuring it. It shows:
- what memory is doing right now;
- what last night changed;
- what a person should check;
- the graph of who and what facts are about: neighborhoods of any size, and clusters;
- **Mindscape**, a page for each person, place and thing;
- for every message, what recall put in front of the agent, and why;
- every setting.

It works on a phone as well as on a desktop.

![The graph: everything Silas has talked about, grouped into clusters, with his facts listed on the right](img/dashboard/graph.webp)

*All screenshots use the synthetic "Silas" life from the [Almanac](https://github.com/jbpayton/almanac) benchmark, not anyone's real memory.*

## Start it

1. **Use Sophia as the memory provider** (see the [quick start](../README.md#quick-start)). The tab reads Sophia's store for the dashboard's active profile: `$HERMES_HOME/plugin-data/sophia/sophia.db`.
2. **Enable the plugin's backend.** Hermes imports a user plugin's dashboard backend only if the plugin is listed in `plugins.enabled`. Sophia still loads as a memory provider either way; this setting only gates the dashboard.

   ```yaml
   plugins:
     enabled:
       - sophia
   ```

3. **Start the dashboard, or restart it.** The backend is loaded when the dashboard starts, so a dashboard that was already running needs a restart.

   ```bash
   hermes dashboard            # http://127.0.0.1:9119
   ```

   Open **Sophia** in the sidebar, or go to `/sophia`.

4. **On a phone.** The dashboard has to be reachable from the phone. Either:
   - bind it to the network with `hermes dashboard --host 0.0.0.0`, which requires a dashboard login (a password or OAuth provider);
   - or keep it on `127.0.0.1` and reach it through a tunnel.

   Below 900 px wide the views move to a tab bar at the bottom, and every control is at least 44 px tall.

The tab never starts anything on its own:
- It reads the store through short-lived read-only connections, so watching can't block the gateway or a night.
- It refreshes while the page is visible:
  - "Right now" every 5 seconds;
  - the recall list every 15 seconds;
  - everything else every 30 seconds.
- It changes memory only when you press a button.

## Overview

![The Overview on a desktop: the Right now strip, last night, what's in memory, and recall this week](img/dashboard/overview.webp)

### Right now

A live strip at the top of the Overview. The pill in the header ("Awake · sleeps at 03:30") follows you to every view.

| Cell | What it shows |
|---|---|
| **The night** | When the next sleep is. It's read from the crontab line that runs `sophia sleep`; with no such line, "Not scheduled". Also how the last night ended and how long it took |
| **Waiting for tonight** | Lines captured since the last night, and any that still lack embeddings |
| **Models** | The embedder, decider and night model: up or down, busy ("working"), and how fast their server answers. A degraded mode shows here with the reason |
| **Last line captured** | When the last line came in, who said it, and the session |
| **Latest recalls** | The last five messages, each with what recall did: how many lines it injected, "Possible matches only", "Nothing needed", or "Nothing found". Select one to open it in Recall |

While a night runs, the first cell shows it:
- the step, out of 16;
- how long the step has taken so far;
- the step's progress, as items done out of the total when that is known;
- the model calls made in the step.

The night writes this as it works, at most every few seconds. If the night's process ends without finishing (killed, or a reboot), the cell says which step it stopped in; the next night reruns the unfinished work.

![Right now while a night runs: step 6 of 16, Integrate, 140 of 380 items](img/dashboard/night-in-progress.webp)

### Last night, what's in memory, recall

- **Last night:**
  - what the last run did: new facts, task cards, facts marked as changed, plans whose date passed without word;
  - how long each step took.
- **What's in memory:**
  - lines kept verbatim, facts, entities and task cards;
  - who said the lines.
- **Recall:** the last seven days of messages by what recall did, with the median number of lines injected and the median time. When every message got memory added, it says so, because that usually means small talk is pulling in more than it needs.

### Needs a look

What a person should check. Every button writes to the same journal as the CLI, with a way back.

![Needs a look and Recent changes](img/dashboard/needs-a-look.webp)

| Item | Why it's here | Buttons |
|---|---|---|
| **A change that may be wrong** | The night retired a fact because a newer one seemed to contradict it (with its confidence). Two facts can both be true, as with a pool trip and a move | **Undo** makes the older fact current again. **Keep** takes it off the list |
| **A plan with no outcome** | A planned fact whose date passed with no word on whether it happened. Recall calls these "unconfirmed" | **It happened** makes it an ordinary fact. **It didn't** marks it cancelled: kept, and recalled only as history. **Leave** takes it off the list |
| **Kept out of memory** | A web page carried instructions aimed at the assistant. The night recognised it and keeps it out of recall from now on | **Seen**. The Recall view shows any message that used it before the night |
| **Recall couldn't find it again** | The night's rehearsal asked a question about a stored fact, and recall missed it | **Open page**, or **Dismiss** |
| **A night step failed** / **Running degraded** | The error, or which model is unavailable and since when | none |

A resolved item stays in place with an **Undo** until you leave the page. The first twelve plans past their date are listed; **Show more** lists the rest.

### Recent changes

The journal, newest first:
- what the night superseded;
- the task cards it wrote;
- web pages it kept out of recall;
- every correction made from the tab, the CLI or the agent's `sophia_correct` tool.

Entries that can be reversed have an **Undo**. An undone entry is struck through.

## Graph

The graph has two views. The picture at the top of this page is **Everything**, with Silas selected: his own cluster in the middle, and around it the move to Denver, Riley and the lake, the librarian job, a concert and the teaching job.

**Neighborhood** shows everything within 1 to 4 hops of one person or thing: the center. It opens on you.
- To change the center, double-click a circle, pick **Explore from here** in its panel, or search.
- The last ring is trimmed to its best-connected members when a neighborhood gets very large, and the graph says how many were left out.
- Your own neighborhood reaches almost everything in one or two hops. Neighborhoods around other people and things are smaller, and show how they connect.

**Everything** shows every person and thing, grouped into clusters: what gets talked about together.
- A soft outline and a name mark each cluster, taken from its best-connected members.
- The list under **Clusters** picks one: the graph zooms to it and dims the rest.
- Clusters are computed from the facts and from which people and things are named in the same lines. A fact about a hub that has facts about everything (usually you) counts for less, so your own facts split into topics instead of one big star. Clusters under three members count as loose.

![A 1-hop neighborhood around Riley, with her facts and her cluster in the panel](img/dashboard/graph-neighborhood.webp)

**To read the graph:**
- **Colour by** switches between clusters and who each circle is (you in violet, the agent in cyan, other speakers in pink).
- Big circles are subjects, the people and things that facts are about.
- Lines are facts. Faint lines join subjects mentioned together; turn them off with **Mentioned together**.
- Drag to move, and scroll or pinch to zoom.

**Line styles** match the filters:

| Line | Meaning |
|---|---|
| Solid | Current |
| Dotted amber | Planned, or past its date with no outcome |
| Dashed grey | Changed, cancelled or retracted |

**The panel** lists every fact about the selection, and its cluster. It has **Open page** and **Explore from here**. It sits on the right on a desktop. On a phone it slides up from the bottom, folded so the graph stays in view: tap its handle to expand it.

The graph's defaults (which view it opens on, and how many hops) are in [Settings](#settings), along with how big clusters are.

## Mindscape

Mindscape is Sophia's wiki: the pages the night builds about each person, place and thing. The agent reads them with `sophia_browse`; here you read them too.

![Spokane's page: what's believed now, each fact with the words it came from, and what it links to](img/dashboard/page.webp)

Each page has:

| Section | What it holds |
|---|---|
| **Date passed, no word** | Unconfirmed plans, with **It happened** / **It didn't** |
| **Believed now** | Current facts |
| **Planned** | Plans still ahead |
| **Before** | Superseded, cancelled or retracted facts, recalled only as history |
| **Every mention** | Lines that name it, plus the lines its facts came from. The agent's own replies are marked as weaker evidence; web pages and lines kept out of recall are tagged |
| **Linked** | The other people and things its facts connect it to |

Every fact shows the verbatim words it came from, who said them and when. **Show in graph** opens the Graph with this page's subject spread out.

## Recall

![A recall where two lines from a prompt-injection page were injected before the night caught it](img/dashboard/recall.webp)

Every message the agent received, newest first, each with what recall did. Select one to see:
- **The gate's reading:** the three shares the decider gave (a general request, none of the memories fits, a memory bears on it), with the 0.8 cutoff marked, and a sentence saying why memory was or wasn't added. It also says when the strong-match rule let memory through regardless.
- **Warnings:**
  - a statement that pulled in many lines;
  - lines from web pages;
  - an injection made mostly of the agent's own replies.
- **Injected:** the lines that went into the prompt, verbatim, with their match score. **Keep out** removes a line from recall (reason required, undoable).
- **What the gate weighed:** the top candidates, and the share the gate gave each one.

Recalls recorded since latency and follow-up tracking was added also show how long recall took and whether the message was read together with the previous one.

## Correcting memory

Corrections change what was *derived*, never the words themselves. Each needs a reason, and each is journaled.

| Action | Where | What changes | Undo |
|---|---|---|---|
| **Someone else said this** | "…" on a fact or a line | The speaker of every line in that message. Facts already drawn from it don't change: retract any that are wrong | Recent changes, or `hermes sophia undo <id>` |
| **This fact is wrong: retract it** | "…" on a fact | The fact stops being recalled; the words stay on record | same |
| **Keep this line out of recall** | "…" on a line, **Keep out** in Recall | The message's lines are flagged and never injected | same |
| **Undo / Keep** a change | Needs a look | The supersession is reversed, or kept and taken off the list | same |
| **It happened / It didn't / Leave** | Needs a look, Mindscape | The plan becomes a fact, is cancelled, or is left unconfirmed | same |

The same journal is readable with `hermes sophia journal`.

For lines relayed by another agent, run `hermes sophia audit-facts`. It lists the facts that don't name the people they're about in the line they came from; `--apply` retracts them, journaled.

## Settings

![Settings: the same fields as Hermes's own settings for Sophia, each showing the value in use](img/dashboard/settings.webp)

Every one of Sophia's settings, grouped:
- **Basics:** names, the model server, and the three models.
- **A server per job:** shown when "Model servers" is per-job.
- **Tuning:** recall, capture, the night, and the graph.

Each field shows the value Sophia uses now, so saving without a change changes nothing. **Find a setting** searches all of them, including ones the current choices hide.

Saving goes through Hermes's own settings API, with the same validation as Hermes's **Plugins** page. The new values apply here at once, to new conversations, and to the next night.

The same settings are in Hermes itself:
- **Plugins**, under the memory provider;
- `hermes memory setup`;
- `hermes config set memory.sophia.<key> <value>`.

Every setting is described in [CONFIGURATION.md](CONFIGURATION.md).

![The same settings on Hermes's Plugins page](img/dashboard/hermes-settings.webp)

## On a phone

![The graph, a Mindscape page, the Overview, and the correction sheet on a phone](img/dashboard/phone.webp)

## Troubleshooting

| You see | Why |
|---|---|
| No Sophia tab | `sophia` isn't in `plugins.enabled`, or the dashboard can't find the plugin: check that `~/.hermes/plugins/sophia/dashboard/manifest.json` exists (the plugin directory, or a link to `hermes_sophia/`) |
| The tab opens but says "Couldn't load this" (Not Found) | The dashboard was started before `sophia` was enabled. Restart it: it loads the plugin's backend only at startup |
| "No memory here yet" | This profile has no Sophia store. Set `memory.provider: sophia` and talk for a while |
| "Not scheduled" under The night | No crontab line runs `sophia sleep`. See [Commands](HOW-IT-WORKS.md#commands) |
| The last run "stopped during" a step | The night's process ended early. The next night reruns what was left |
| A crowded graph | Use a neighborhood with fewer hops, focus one cluster, turn filters or "Mentioned together" off, or search |
