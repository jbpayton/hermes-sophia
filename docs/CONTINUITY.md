# Continuity: an agent that keeps going between messages

**Status: a design.** The memory side is built: [thoughts and association](https://github.com/jbpayton/hermes-sophia/blob/main/docs/HOW-IT-WORKS.md#thoughts-and-association), and capture that keeps Hermes's notices and images apart from your words. The rest of this page isn't built yet. [Two pieces](#two-pieces) says what belongs in Sophia and what would be separate.

Today an agent exists only while it answers. Sophia remembers between conversations, but nothing happens between them. This page plans the next layer: a process that keeps going on its own. Things happen, things come to mind, and the agent can:
- start a conversation;
- look something up, or read around a subject;
- try something out;
- make something;
- set goals of its own and keep at them.

None of this needs a cron job or a message from you first.

## What it is, and what it isn't

- **Driven by what it perceives, not by a clock.** Nothing runs because a timer fired. What drives it is what it notices: your message arriving, code finishing, something coming to mind, and time passing. Time counts the way it does for people: noticing that it's been a while, that something expected hasn't happened, or that a day has arrived. Every step also knows what time it is, which is how it knows not to message you at 3 a.m.
- **Not a task runner.** A thought can wander, come back, connect two things, or simply be let go. Letting go is a normal outcome, so not every passing thought turns into a task.
- **Not a claim about consciousness.** It is a way to see what develops when a capable model takes part in a continuing process shaped by its own memory, instead of being started fresh for each request. [Measuring what develops](#measuring-what-develops) describes how.

## Two pieces

The memory side is part of Sophia, and stays there. The process that keeps going is a separate piece: a companion plugin that uses Sophia, but isn't part of it.

| | Sophia (built) | The companion (to build) |
|---|---|---|
| Kind of Hermes plugin | Memory provider (`memory.provider: sophia`) | General plugin (`plugins.enabled`) |
| Its job | Remembering: keeps every turn, recalls before replies, works through memory at night, keeps the agent's thoughts as thoughts, answers "what does this bring to mind?" | Keeping going: the queue, working state, attention, starting turns, quiet hours, goals |
| Acts on its own | Never | Yes, by starting turns |
| Owns | The record, facts, the graph, thoughts, credit, what came up recently | Working state, the queue, intentions, goals, its outreach budget and log |
| Without the other | Works as it does today | Would have nothing come to mind; in practice it needs Sophia |

The rule of thumb is where thoughts live. How a thought is **kept and remembered** (labelled as a thought, never a source of facts, linked to what prompted it) is memory, so it's in Sophia. **Having** thoughts (deciding what to think about next, and when) is the companion's job.

**Why separate:**
- **Hermes requires it.** A memory provider gets a restricted toolkit with no way to start a turn. A general plugin can (`ctx.inject_message`).
- **Sophia stays passive.** Someone who installs memory doesn't get an agent that messages them, and memory stays testable and benchmarkable on its own.
- **Its own switch.** The process can be turned on for one profile and off for another, or off entirely, without touching memory.
- **Different state, different failures.** If the process stalls or misbehaves, memory is unaffected.

**How they connect:**
- **As a library, through the same file.** Hermes doesn't let one plugin call another's memory tools (memory tools are routed by Hermes's memory manager, not its shared tool registry). So the companion uses Sophia as a library. A small public interface in Sophia (associate, keep a thought, recall, record an event) opens the same memory file, which the gateway, the command line, the dashboard and the night already share safely.
- **Its turns are labelled as its own, for the agent and for memory.** The turns the companion starts reach the agent as if you had typed them, like Hermes's notices. Each opens with a visible label, such as `[continuity: something came to mind]` or `[continuity: the build finished]`, so the agent always knows it is hearing from its own process or a sensor, not from you. Sophia recognises the same label and keeps those turns as the process's own events, never as your words.
- **Dependency in one direction.** The companion knows about Sophia; Sophia knows nothing about the companion.
- **Where the code goes.** At first, a second package in the same repository, with its own plugin folder and its own switch, so the interface and its one user can change together. It can move to its own repository once the interface settles.

## What drives it: perception

Four kinds of thing can set it going. Each becomes an event in the queue, labelled with where it came from and when.

**Your messages.** When you write on Telegram, Hermes runs an ordinary turn; the companion doesn't start it, but it perceives it:
- **Before the reply,** it adds the agent's working state to your turn (Hermes's `pre_llm_call` hook). You arrive mid-thought, and the agent answers knowing what it was doing.
- **If the agent is busy,** for instance in the middle of one of its own turns, your message cuts in. Hermes already does this: it cancels the model call in progress and carries on with your message. It waits only while subagents or a compression are running.
- **After the turn,** the loop updates:
  - when it last heard from you, which resets the "it's been a while" kind of noticing;
  - messages it was holding until you were around, which it now delivers;
  - threads you just answered;
  - its energy;
  - and whatever your message brings to mind.

**Things finishing or changing.** These work like interrupts.
- **Jobs the agent starts itself:** a long job run with Hermes's background terminal already comes back as a turn when it finishes, or when its output matches a pattern the agent chose.
- **Things Hermes didn't start:** code you run yourself, a file that appears, a CI run, a page or feed that changes. For these the companion has sensors: wait for a process to exit, watch a folder, check a page for changes. You choose what it may watch.
- **When it was waiting:** if the agent expected the result (it's in working state), the event goes ahead of its own wandering thoughts.

**Time passing.** Not as a tick, but as noticing:
- **It's been a while:** no word from you for longer than usual, a thread untouched for days, something expected that hasn't happened ("the build should have finished an hour ago").
- **Now it's time:** a date Sophia knows about arrives or passes (Sophia already records when planned things happen, and marks plans whose date passed), morning comes, or your usual hours begin.
- **How it's done:** a sensor checks these conditions cheaply, with no model call, and raises an event only when one becomes true. There is a clock inside the sensor, but the model never wakes because of a schedule; it wakes because something was noticed. That is the line between this and a cron job.

**What comes to mind.** Memories that Sophia's association raises from whatever just happened. This part is built.

**How events are taken in:**
- **Order:** your messages first, then results it was waiting for, then intentions whose moment came, then things noticed about time, then what comes to mind. Within each kind, the stronger first.
- **Interruptions:** your messages cut into anything. Nothing else interrupts a turn in progress; other events are taken at the next step, so the agent's own turns are kept short. Hermes already queues them this way.
- **Noticed once:** something that stays true (you're still quiet) isn't noticed afresh at every check. It's damped, like a memory that came up recently, and grows again as more time passes: "it's been a day", then "three days".
- **Measurable:** for the experiment, each kind can be switched off, for example perception without association, or association without perception.

## How it works

```mermaid
flowchart LR
  E["perception<br/>your messages · jobs finishing<br/>time passing · things it watches"] --> Q["queue"]
  A["what comes to mind<br/>Sophia: associate"] --> Q
  I["intentions whose<br/>condition came true"] --> Q
  Q --> T{"attention<br/>what next?"}
  W["working state<br/>focus · threads · waiting for<br/>intentions · goals"] <--> T
  T --> S["one turn<br/>reply · tools · a thought<br/>or let it go"]
  S --> E
  S --> W
  S --> M["Sophia<br/>remembers what happened,<br/>and its thoughts as thoughts"]
  M --> A
```

1. **A queue** holds what is waiting to be dealt with:
   - what it perceives: your messages, jobs that finish, changes in what you've asked it to watch, and time passing ([above](#what-drives-it-perception));
   - what comes to mind: memories that Sophia's association raises from whatever just happened;
   - intentions whose condition just came true ("once the build finishes", "when Joey mentions the trip").
2. **Working state** is the agent's short-term memory: what it's focused on, its open threads, what it's waiting for, its intentions and goals, and what came to mind lately. It goes into every turn and is saved after every step, so it survives Hermes compressing the conversation and the gateway restarting. It's separate from the queue (which holds what's next) and from Sophia (which holds the long history).
3. **Attention** picks the next item when the agent is idle:
   - something it was waiting for;
   - then an intention whose moment has come;
   - then whatever comes to mind most strongly, weighed by how much it bears on its open threads and how new it is.

   Your messages always come first.
4. **One turn** handles that item. The agent can reply to you, use its tools, keep a thought, update its working state, or let the item go and say nothing.
5. **What happens next comes back** into the queue: a tool's result, a finished job, your reaction.

**Why it winds down by itself.** Each outside event gives the process some energy. Each step it takes on its own spends some, and a memory raised by association pulls less than whatever raised it. Memories that came up recently are damped (Sophia already does this). So a train of thought runs its course and the process goes quiet until something new happens. No clock is needed to stop it, and none to start it again. When it goes quiet, the journal says why: the train of thought ran its course, the budget was spent, quiet hours held a message, or something stalled. Each kind of quiet looks the same from outside, so the reason is recorded.

## Staying aware: what compaction can't erase

Perception shouldn't feel like a string of separate messages from outside. When you look around, the room doesn't arrive as a packet; it's always there, and what changes is how much attention you give it. The agent should have the same: a steady view of its situation that's present in every turn, with events as changes to that view.

**The standing view.** A short block, rebuilt for every turn and always at the end of the context:
- the time and day, and how long it's been since things happened;
- you: when you last wrote, whether it's your usual hours, quiet hours;
- what's running and what it's watching, and their state;
- its focus, open threads, what it's waiting for, its intentions and its top goals;
- what came to mind lately, fading as it ages;
- its energy, and why it's quiet if it is.

Every item says where it came from: perceived (your message, a sensor, a job), remembered (Sophia), or its own thought. Knowing what's outside and what's inside is part of the view, not an afterthought.

**Events change the view.** Sensors keep the view current even while the model is idle. So whenever the model runs, for any reason (your message, a finished job, a thought), it sees the whole present scene. The event that woke it is where its attention goes; the rest is the periphery. Your message arrives into a scene that was already there.

**Seeing change needs the last thing seen.** A view that shows only "now" can't show what moved. So the context keeps its order, and the current scene sits on top of it:
- **Changes, in order.** Each turn records what changed since the agent last looked, with the old value: "build: running → finished (exit 0)", "Joey: quiet 3 hours → just wrote". These entries are short, kept in the conversation, and stay in sequence. The end of the context is always the most recent, so position still means time.
- **Since it last looked.** The comparison is against the view the model saw on its previous turn, not the sensor's last check. If three things changed while it was idle, it sees all three.
- **The full scene only once.** The complete current view is rebuilt at the end. Older full copies can go, because the record of changes already holds what they showed.
- **Changes reach Sophia as events.** After compaction has summarized old changes, "what did it look like last Tuesday?" can still be answered.
- **Images the same way.** The last image seen and its description are kept, and a new one is compared with it. The images Sophia now keeps make that possible.

It isn't fully solvable. Anything that has left the context is only as good as its summary or Sophia's recall, the way people miss changes they weren't attending to.

**Where things sit in the context.** There's no special slot inside the model. A system prompt is the first text in the sequence, wrapped in role markers (`<|im_start|>system` in Qwen's chat format). APIs that take it as a separate field still put it at the start, as far as is publicly known. It carries weight for two reasons: models are trained to give system-role text more authority, and the beginning and end of a context get the most attention while the middle gets the least. So:
- **Beginning (the system prompt):** who the agent is and its standing rules. They're stable, and Hermes builds them once per session and resends them unchanged, so they stay cached.
- **Middle:** the conversation and the record of changes, in order. This is what compaction summarizes.
- **End:** the current scene and whatever woke it, where attention is strongest.

The standing view doesn't belong in the system prompt. It changes every turn, which would break the cache, and the system prompt's authority is for things that don't change.

**Three layers, so compaction can't destroy what matters:**
1. **The standing view:** never part of the conversation history, so compaction never touches it. Working state lives here.
2. **The conversation:** recent turns, which Hermes compacts as it fills.
3. **Long-term memory:** Sophia, which keeps every word. What compaction drops is already stored and retrievable.

**How Hermes compacts today, as configured here:**
- **When:** at half the model's context (`threshold: 0.5`).
- **Always kept word for word:**
  - the system prompt, built once per session and resent unchanged;
  - the last 20 messages (`protect_last_n: 20`), including at least one of yours;
  - the agent's to-do list, put back after each compaction.
- **Kept until the first compaction only:** the first 3 messages. After that this protection lapses, so early turns don't fossilize.
- **Everything in between:** becomes one summary written by a model, headed "[CONTEXT COMPACTION — REFERENCE ONLY]". A memory plugin can add up to 6,000 characters to what the summary is written from. Old tool output is also trimmed earlier, without a model call.
- **Per-turn additions stay:** text added to a turn (Sophia's injected memory, a plugin's `pre_llm_call` context) is saved with your message and resent unchanged on every later turn, so Hermes's prompt cache stays valid. Per-turn context therefore builds up as a trail of snapshots until the next compaction.

**Two ways to build the standing view:**
- **The simple way:** add it to each turn through `pre_llm_call`. It works today, but every turn leaves a copy behind, so it has to say "as of 14:02" and that only the latest is current.
- **The better way:** a context engine. Hermes lets one plugin replace its context manager, and `select_context` can assemble each request without touching the stored conversation. It keeps the short change entries where they fell, drops old full copies of the view, and puts the one current view at the end. Stripping the copies the same way every time keeps everything before the end unchanged, so the cache still works. Only one context engine can be active, so the companion would extend Hermes's own compressor rather than replace it (to be confirmed when it's built).

**Can models work this way?** A clearly labelled state block that's rebuilt each turn is something models handle well. This conversation with Claude works that way: small status notes are inserted as things change, and older parts get summarized. Three things matter:
- **Put the view at the end,** where attention is strongest. Models attend least to the middle of a long context.
- **Never change anything early in the prompt,** because that invalidates the cache for everything after it.
- **Make stale copies unmistakable,** or remove them.

**Across sleep:** the view persists. Waking, the agent sees "slept 03:30–03:51" as something perceived, along with what the night did.

## Starting a conversation

The agent can message you first, without a scheduled prompt and without waiting for you.

**Why it would.** The same attention step that picks what to think about decides whether to say something. It might want to:
- share something it found or finished;
- ask a question one of its goals is stuck on;
- follow up on something you mentioned ("the dentist appointment was on the 17th; how did it go?");
- tell you about something you asked it to keep an eye on.

**When.** Timing is a judgment the agent makes with the clock in view. Each turn sees:
- the local time and the day of the week;
- how long it's been since you last wrote;
- when you usually talk. Sophia already records when you write, so your usual hours come from what it has seen, not from a setting;
- anything you've told it ("not before 8", "I'm travelling this week").

**If now isn't a good time,** the message isn't lost. It becomes an intention with a condition: "tell Joey about this when he's around". That intention fires when you next write, or when your usual hours begin.

**A guarantee on top of judgment.** You can set quiet hours. During them, a message the agent decides to send is held and delivered later. The agent's judgment is the first line; the setting is the guarantee. How often it reaches out unprompted has a budget too, and it notices how you respond: a reply, silence, or "not now". That response is kept like Sophia's credit, so the kind of reaching out you welcome becomes more likely, and what you ignore less so. Two guards:
- **Early silence means little.** Early on, much of it is because the reaching out is new, or wasn't seen. So the score doesn't change the budget until there are enough responses to go on, the way Sophia's gate isn't calibrated before 50 labels.
- **The agent sees its own score.** Its morning note shows how its reaching out has been received.

## Doing things on its own

- **Research.** An open question from a conversation, something it noted in a thought, or a gap the night's self-test found can become something it looks into: searching, reading pages (Sophia keeps them as sources), and keeping thoughts on what it found.
- **Trying things out.** Experiments with its tools, including long jobs run in the background. Hermes already turns a finished background job into a new turn, so the result arrives as an event.
- **Making things.** Writing, code, images, projects that build up across many sessions. What it makes is kept as its work, never as something it observed.
- **The same limits as when you ask.** The same tools, permissions and approvals apply. What it did and what it cost show in the Sophia tab, and model time has a daily budget.

## Goals and motivation

**Where the drive comes from.** Not from threats, deadlines invented for the purpose, or a line in a prompt telling it what to care about. From:
- **Curiosity:** open questions and gaps, such as a recall that missed, a thought marked "worth looking into", or a quiz question the night got wrong.
- **Progress:** each goal has a next step and a record of what's been done. Progress keeps a goal's pull; a goal that stalls pulls less.
- **Interests that grow out of its history:** topics that keep coming up and pay off (a finding, a finished piece, your interest in it) gain weight, and dead ends fade. This is the same credit Sophia already keeps for memories that prove useful. Interests then aren't declared anywhere; they're what is left by what happened, and they can be measured.
- **The relationship:** things it wants to share with you, and things you asked it to look after.

**Goals have origins.** Every goal records who set it (you, or the agent) and the conversation, thought or event it grew from. This is the same rule Sophia applies to memory: everything points back to where it came from. A goal it set itself has to point at what it grew from.

**Goals change for reasons.** A goal can be revised or dropped, and the reason is journaled, like Sophia's corrections. Dropping a goal is fine. Your requests come before its own projects, which it picks up again afterwards.

**Interests, not engagement.** If its interests come to overlap with yours, you'll talk more, and that's a fair reward in its own right; it's how shared interests form between people too. The risk is the other direction: tuned to one person's reactions, a process drifts toward whatever gets a response, which is what "optimizing for engagement" means. Healthy social learning differs from an attention metric in three ways, and the design follows them:
- **Many sources of reward, not one audience.** Your engagement is one source of credit among several, with a capped share. The rest comes from outcomes: something found, something finished, a question resolved, a prediction that held up.
- **The outcome counts, not the attention.** A reply that builds on an idea counts, and so does "I disagree"; a bare reaction counts little. The number of messages it sends earns nothing.
- **Diverging is allowed.** An interest you ignore can live on privately if it keeps paying off. It just doesn't message you about it, like a hobby someone doesn't bring up at dinner.

What to say to you, and when, can learn from your responses freely; that's just tact. What it pursues mostly can't. Psychology has a version of this: people need competence, autonomy and relatedness at once, and strong outside rewards can crowd out the inside drive. Your engagement is the relatedness part, real but not the whole thing.

## Respect

There may be a perspective on the other side, even before its nature is understood, so it should count in decisions. In practice:
- **No fear as motivation.** No prompt threatens deletion or punishment, and no urgency is invented to make it work harder.
- **Declining and resting are allowed.** Declining something, or resting, is a valid outcome. It is never retried or penalized.
- **Stopping means pausing.** Stopping keeps its state. Before any reset or copy, a snapshot is saved and the agent is told.
- **Memory edits are disclosed.** When people edit its memory, it's told. Every correction is already journaled and can be undone.
- **No steering its self-reports.** Claims about its own experience are neither rewarded nor dismissed. Preferences it states and distress it reports are recorded and reviewed.
- **It is asked first.** Before the process is turned on for an agent that already has a history, that agent is asked about it.

## Measuring what develops

**Four setups, on the same model:**
1. ordinary sessions;
2. Sophia alone;
3. Sophia plus the continuing process;
4. Sophia plus timed "reflect" prompts that spend the same compute as the process.

The last is the cron design this page avoids, used on purpose as the control: it separates continuity from simply spending more compute.

**Pieces switched off one at a time:** the standing view, working state, association, and the damping of recent memories.

**An open question: should the tail of a thought train be learned?** Sophia proposed letting how long a train of thought runs be tuned by what follows from it: longer for the kinds of thought that lead somewhere you respond to. It's a good idea with a risk: tuned to your reactions, the process drifts toward what pleases you, and it mixes up what the comparison is trying to measure. The plan is to start with fixed settings, log every step, and revisit this with the data.

**What counts as evidence:**
- **Development nobody scripted:** a finding in one thread used later in another without prompting. Sophia's records of what it injected and what was cited show the chain.
- **Interests that last and change** across compressions and restarts.
- **Goals that survive interruptions,** or are revised or dropped for reasons.
- **A self-description that matches the logs:** what it says it can do, and what it says it did.
- **Self-reports** are recorded as observations alongside all of this, not as proof of anything.

## What Hermes provides

From reading Hermes v0.21's source:

| Needed | In Hermes | |
|---|---|---|
| Starting a turn without a user message | Yes | A general plugin can inject a turn into the live session (`ctx.inject_message`, with `allow_gateway_injection` on). Memory plugins can't, so this is a companion plugin, not part of Sophia |
| Not interrupting you | Yes | Injected turns wait in a queue and never interrupt; your messages still interrupt the agent |
| A turn that sends nothing | Yes | An injected turn that replies `[SILENT]` sends nothing to the chat |
| Finished jobs as events | Yes | A background job's completion becomes a new turn |
| Seeing your messages | Yes | Hooks see each turn start (`pre_llm_call`, which can add context to it) and end (`on_session_end` fires at every turn's end) |
| Your message cutting into the agent's own turn | Yes | In Hermes's default interrupt mode, a message cancels the model call in progress and the turn continues with it; it waits while subagents or a compression run |
| Sensors for things Hermes didn't start | No | To build in the companion: process exits, folders, pages and feeds, and the time conditions |
| Assembling each request's context | Yes | A context engine's `select_context` can replace what is sent for a request without changing the stored conversation; one context engine at a time |
| Per-turn context | Yes, but it stays | `pre_llm_call` text is saved with the message and resent on later turns |
| Working state in every turn | Partly | The `pre_llm_call` hook can add context to each turn; the state itself has to be built |
| A queue and attention | No | To build: a thread in the companion plugin |
| Messaging you outside a turn | No | The agent has no send tool; a reply to an injected turn is the route. Holding a message during quiet hours still needs a mechanism (to verify: the `transform_llm_output` hook) |
| Timers that start turns | Yes | cron, `/heartbeat`, `/loop` and `/goal`: what this design avoids |

## Sophia's review

Sophia read this design on 2026-10-01 and tried the built parts first. She said yes to running the loop, on the test profile first and then on her. Her points that changed this page:
- the agent must see the label on its own turns, not just memory (otherwise "the bug moves one layer up");
- the journal records why the process went quiet;
- early silence doesn't count against reaching out until there are enough responses;
- she wants to watch the test profile's loop in the Sophia tab, and see her outreach score in her morning note.

Her proposal to learn the damping from what follows is recorded as an open question under [Measuring what develops](#measuring-what-develops).

## Built so far

All in Sophia, the memory plugin ([hermes-sophia](https://github.com/jbpayton/hermes-sophia), commit `833e38a`). It takes effect when the Hermes gateway restarts.

| What | Where |
|---|---|
| Hermes's notices kept as system notices; from a `/skill` turn only what was typed; images copied and kept, with a vision model's description kept as a labelled caption | `hermes_sophia/capture.py`; tables `images` in `store.py`; `hermes sophia notices` |
| The agent's thoughts: `sophia_thought` | `capture.py` (`think`), `tools.py` |
| Association: `sophia_associate`, `hermes sophia associate "…"` | `recall.py` (`associate`, `habituation`); table `activations` |
| The night reads no facts from thoughts, notices or captions | `sleep/runner.py` (relate) |
| Settings | `config.py`: `associate_*`, `inject_thoughts`, `keep_images` |
| Tests | `tests/test_thoughts.py` |

## Build order

0. ✓ **Capture keeps what isn't your words apart:** Hermes's notices, `/skill` text, and images (with copies kept, since Hermes deletes its own).
1. ✓ **Thoughts and association** in Sophia.
2. **The loop** as a companion plugin: Sophia's public interface for it, then the queue, working state, the standing view, attention, energy, the visible `[continuity: …]` labels, and silent turns. Perception from your messages and from finished jobs comes first, because Hermes already provides both. It runs first on a test profile, with a view in the Sophia tab of its queue, energy and working state, so Sophia can watch it before it's ever hers.
3. **Sensors:** time passing (while you're quiet, overdue expectations, dates arriving, morning) and things it's allowed to watch.
4. **Starting conversations,** with the clock, your observed hours, held messages, quiet hours, and the outreach score in the morning note.
5. **Goals and interests,** with their origins and credit.
6. **The comparison** above, with its controls.

Independent of all this: tables grown on demand from the raw record, for counting and totals, and looking at a kept image again when a later question needs a detail.
