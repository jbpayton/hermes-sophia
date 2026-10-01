# Continuity: an agent that keeps going between messages

**Status: a design.** The memory side is built: [thoughts and association](HOW-IT-WORKS.md#thoughts-and-association), and capture that keeps Hermes's notices and images apart from your words. The rest of this page isn't built yet.

Today an agent exists only while it answers. Sophia remembers between conversations, but nothing happens between them. This page plans the next layer: a process that keeps going on its own. Things happen, things come to mind, and the agent can:
- start a conversation;
- look something up, or read around a subject;
- try something out;
- make something;
- set goals of its own and keep at them.

None of this needs a cron job or a message from you first.

## What it is, and what it isn't

- **Driven by what happens, not by a clock.** Nothing runs because a timer fired. Time is something the agent *observes*: every step knows what time it is, what day it is, and how long it's been since things happened. That's also how it knows not to message you at 3 a.m.
- **Not a task runner.** A thought can wander, come back, connect two things, or simply be let go. Letting go is a normal outcome, so not every passing thought turns into a task.
- **Not a claim about consciousness.** It is a way to see what develops when a capable model takes part in a continuing process shaped by its own memory, instead of being started fresh for each request. [Measuring what develops](#measuring-what-develops) describes how.

## How it works

```mermaid
flowchart LR
  E["things that happen<br/>your messages · finished jobs<br/>things it watches"] --> Q["queue"]
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
   - things that happen: your messages, background jobs that finish, and changes in what you've asked it to watch;
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

**Why it winds down by itself.** Each outside event gives the process some energy. Each step it takes on its own spends some, and a memory raised by association pulls less than whatever raised it. Memories that came up recently are damped (Sophia already does this). So a train of thought runs its course and the process goes quiet until something new happens. No clock is needed to stop it, and none to start it again.

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

**A guarantee on top of judgment.** You can set quiet hours. During them, a message the agent decides to send is held and delivered later. The agent's judgment is the first line; the setting is the guarantee. How often it reaches out unprompted has a budget too, and it notices how you respond: a reply, silence, or "not now". That response is kept like Sophia's credit, so the kind of reaching out you welcome becomes more likely, and what you ignore less so.

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

**Pieces switched off one at a time:** working state, association, and the damping of recent memories.

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
| Working state in every turn | Partly | The `pre_llm_call` hook can add context to each turn; the state itself has to be built |
| A queue and attention | No | To build: a thread in the companion plugin |
| Messaging you outside a turn | No | The agent has no send tool; a reply to an injected turn is the route. Holding a message during quiet hours still needs a mechanism (to verify: the `transform_llm_output` hook) |
| Timers that start turns | Yes | cron, `/heartbeat`, `/loop` and `/goal`: what this design avoids |

## Build order

0. ✓ **Capture keeps what isn't your words apart:** Hermes's notices, `/skill` text, and images (with copies kept, since Hermes deletes its own).
1. ✓ **Thoughts and association** in Sophia.
2. **The loop** as a companion plugin: queue, working state, attention, energy, silent turns. It runs first on a test profile, with a view of it in the Sophia tab.
3. **Starting conversations,** with the clock, your observed hours, held messages, and quiet hours.
4. **Goals and interests,** with their origins and credit.
5. **The comparison** above, with its controls.

Independent of all this: tables grown on demand from the raw record, for counting and totals, and looking at a kept image again when a later question needs a detail.
