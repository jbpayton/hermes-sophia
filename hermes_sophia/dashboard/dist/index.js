/* Mindscape — the Hermes dashboard tab for watching and curating Sophia's memory.
 * Plain IIFE against the dashboard's plugin SDK (its React, its authenticated fetch); no build step.
 * Views: Overview (live state, last night, what needs a look), Graph, Pages, Recall. Sub-views live in the URL
 * query (?mv=graph, ?mv=pages&mk=<entity>, ?mv=recall&mk=<id>): the dashboard routes plugin tabs by exact path and
 * rewrites the URL on load (it keeps other query parameters, but not the hash). */
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  var React = SDK.React;
  var useState = SDK.hooks.useState, useEffect = SDK.hooks.useEffect, useCallback = SDK.hooks.useCallback,
      useMemo = SDK.hooks.useMemo, useRef = SDK.hooks.useRef, useContext = SDK.hooks.useContext;
  var h = React.createElement;
  var API = "/api/plugins/sophia";

  function get(path) { return SDK.fetchJSON(API + path); }
  function post(path, body) {
    return SDK.fetchJSON(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }
  function errText(e) {
    var s = String((e && e.message) || e || "error");
    var m = s.match(/"detail"\s*:\s*"([^"]+)"/);
    return m ? m[1] : s.replace(/^\d+:\s*/, "");
  }
  function cx() { return Array.prototype.filter.call(arguments, Boolean).join(" "); }

  // ------------------------------------------------------------------ formatting
  function pad(n) { return String(n).padStart(2, "0"); }
  function clock(ts) { var d = new Date(ts * 1000); return pad(d.getHours()) + ":" + pad(d.getMinutes()); }
  function day(ts) { return new Date(ts * 1000).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }); }
  function stamp(ts) { return ts ? day(ts) + " · " + clock(ts) : ""; }
  function ago(ts) {
    if (!ts) return "";
    var s = Date.now() / 1000 - ts;
    if (s < 60) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  }
  function until(ts) {
    var s = ts - Date.now() / 1000;
    if (s <= 60) return "any moment";
    if (s < 3600) return "in " + Math.round(s / 60) + " min";
    return "in " + Math.floor(s / 3600) + " h " + Math.round((s % 3600) / 60) + " min";
  }
  function dur(sec) {
    sec = Math.round(sec || 0);
    if (sec < 60) return sec + " s";
    var m = Math.round(sec / 60);
    return m < 60 ? m + " min" : Math.floor(m / 60) + " h " + (m % 60) + " min";
  }
  function pct(p) { return Math.round((p || 0) * 100) + "%"; }
  function trunc(s, n) { s = s || ""; return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function sentence(f) { return (f || []).filter(Boolean).join(" "); }
  function capital(s) { s = s || ""; return s.charAt(0).toUpperCase() + s.slice(1); }
  function nightDate(id) {
    var m = /^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)/.exec(id || "");
    if (!m) return id === "manual" ? "by hand" : (id || "");
    return day(new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]).getTime() / 1000) + " · " + m[4] + ":" + m[5];
  }

  // ------------------------------------------------------------------ icons
  var ICONS = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    graph: '<circle cx="12" cy="12" r="3"/><circle cx="4.5" cy="6" r="2"/><circle cx="19.5" cy="6" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="18.5" r="2"/><path d="M6.2 7.2 9.6 10M17.8 7.2 14.4 10M7.4 17.6 10 14.2M16.6 17.2 14 14.2"/>',
    book: '<path d="M2 4h6a4 4 0 0 1 4 4v12a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v12a3 3 0 0 1 3-3h7z"/>',
    message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    back: '<path d="m15 6-6 6 6 6"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    check: '<path d="m5 12 5 5 9-10"/>',
    more: '<path d="M5 12h.01M12 12h.01M19 12h.01" stroke-width="3"/>'
  };
  function Icon(p) {
    return h("svg", { width: p.size || 20, height: p.size || 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
      strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true",
      dangerouslySetInnerHTML: { __html: ICONS[p.name] || "" } });
  }

  // ------------------------------------------------------------------ hooks
  function useApi(path, every) {
    var st = useState({ data: null, error: null, loading: true }), state = st[0], set = st[1];
    var seq = useRef(0);
    var load = useCallback(function () {
      if (!path) return Promise.resolve();
      var my = ++seq.current;
      return get(path).then(function (data) {
        if (my === seq.current) set({ data: data, error: null, loading: false });
      }, function (e) {
        if (my === seq.current) set(function (s) { return { data: s.data, error: errText(e), loading: false }; });
      });
    }, [path]);
    useEffect(function () {
      set({ data: null, error: null, loading: true });
      load();
      if (!every) return undefined;
      var id = setInterval(function () { if (document.visibilityState === "visible") load(); }, every);
      return function () { clearInterval(id); };
    }, [load, every]);
    return { data: state.data, error: state.error, loading: state.loading, reload: load };
  }

  function useMedia(q) {
    var st = useState(function () { return window.matchMedia(q).matches; });
    useEffect(function () {
      var mq = window.matchMedia(q);
      var f = function () { st[1](mq.matches); };
      mq.addEventListener("change", f);
      f();
      return function () { mq.removeEventListener("change", f); };
    }, [q]);
    return st[0];
  }

  var VIEWS = [["overview", "Overview", "grid"], ["graph", "Graph", "graph"], ["pages", "Pages", "book"], ["recall", "Recall", "message"]];
  function parseRoute() {
    var q = new URLSearchParams(window.location.search);
    var view = q.get("mv") || "", arg = q.get("mk") || "";
    var known = VIEWS.some(function (v) { return v[0] === view; });
    return { view: known ? view : "overview", arg: known ? arg : "" };
  }
  function routeHref(view, arg) {
    var q = new URLSearchParams(window.location.search);
    if (view && view !== "overview") q.set("mv", view); else q.delete("mv");
    if (arg) q.set("mk", arg); else q.delete("mk");
    var qs = q.toString();
    return window.location.pathname + (qs ? "?" + qs : "");
  }
  function useRoute() {
    var st = useState(parseRoute);
    useEffect(function () {
      var f = function () {
        var r = parseRoute();
        st[1](function (old) { return old.view === r.view && old.arg === r.arg ? old : r; });
      };
      window.addEventListener("popstate", f);
      return function () { window.removeEventListener("popstate", f); };
    }, []);
    var go = useCallback(function (view, arg) {
      var next = routeHref(view, arg);
      if (next === window.location.pathname + window.location.search) return;
      window.history.pushState(window.history.state, "", next);
      // the dashboard's router listens for popstate, so it (and its ?profile= keeper) sees the new query too
      window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
      window.scrollTo(0, 0);
    }, []);
    return [st[0], go];
  }

  // Shared actions: toasts with an Undo, and a signal that makes every view reload after a change.
  var Ctx = React.createContext(null);

  // ------------------------------------------------------------------ small pieces
  function Btn(p) {
    return h("button", { type: "button", className: cx("sm-btn", p.primary && "sm-btn-primary", p.small && "sm-btn-small", p.className),
      onClick: p.onClick, disabled: p.disabled, "aria-label": p.label, title: p.title }, p.children);
  }
  function IconBtn(p) {
    return h("button", { type: "button", className: cx("sm-iconbtn", p.className), onClick: p.onClick, "aria-label": p.label,
      title: p.label, "aria-pressed": p.pressed }, h(Icon, { name: p.icon, size: p.size || 20 }));
  }
  function Card(p) {
    return h("section", { className: cx("sm-card", p.className), "aria-label": p.title },
      (p.title || p.aside) && h("div", { className: "sm-card-head" },
        p.title && h("h2", { className: "sm-h2" }, p.title),
        p.count != null && h("span", { className: cx("sm-count", !p.plainCount && (p.count ? "sm-count-open" : "sm-count-clear")) }, p.count),
        p.aside && h("div", { className: "sm-card-aside" }, p.aside)),
      p.children);
  }
  function Empty(p) { return h("div", { className: "sm-empty" }, p.children); }
  function Loading() { return h("div", { className: "sm-empty", role: "status" }, "Loading…"); }
  function Failed(p) {
    return h("div", { className: "sm-failed", role: "alert" }, h("strong", null, "Couldn't load this. "), p.error,
      p.retry && h(Btn, { small: true, onClick: p.retry }, "Try again"));
  }
  function Bar(p) {   // stacked horizontal bar: [{v, color, label}]
    var total = p.parts.reduce(function (a, x) { return a + (x.v || 0); }, 0) || 1;
    return h("div", { className: "sm-bar", role: "img", "aria-label": p.parts.map(function (x) { return x.label + " " + x.v; }).join(", ") },
      p.parts.map(function (x, i) {
        return x.v ? h("span", { key: i, style: { width: (100 * x.v / total) + "%", background: x.color } }) : null;
      }));
  }
  function Legend(p) {
    return h("ul", { className: "sm-legend" }, p.parts.map(function (x, i) {
      return h("li", { key: i }, h("span", { className: "sm-swatch", style: { background: x.color } }), h("span", { className: "sm-legend-label" }, x.label),
        h("span", { className: "sm-legend-n" }, x.v));
    }));
  }
  function Quote(p) {
    return h("blockquote", { className: "sm-quote" }, "“", p.children, "”");
  }

  var VERDICT = {
    injected: ["Memory injected", "var(--sm-cyan)"],
    possible: ["Possible matches only", "var(--sm-amber)"],
    general: ["Nothing needed", "var(--sm-quiet)"],
    nothing_found: ["Nothing found", "var(--sm-grey)"],
    closed: ["Gate closed", "var(--sm-grey)"],
    degraded: ["Degraded", "var(--sm-rose)"]
  };
  function VerdictChip(p) {
    var v = VERDICT[p.verdict] || [p.verdict, "var(--sm-grey)"];
    return h("span", { className: "sm-chip" }, h("span", { className: "sm-dot", style: { background: v[1] } }),
      p.verdict === "injected" && p.n != null ? p.n + " line" + (p.n === 1 ? "" : "s") : v[0]);
  }

  function statusGroup(e) {
    if (e.status === "unconfirmed") return "check";
    if (e.status === "superseded" || e.status === "cancelled" || e.status === "retracted") return "before";
    if (e.modality === "planned") return "planned";
    return "now";
  }
  var BADGE = { now: "Now", planned: "Planned", check: "Check", before: "Before" };
  function Badge(p) { return h("span", { className: "sm-badge sm-badge-" + p.group }, BADGE[p.group] || p.group); }

  var ROLE = { user: ["You", "var(--sm-violet)"], agent: ["The agent", "var(--sm-cyan)"], speaker: ["Someone who speaks", "var(--sm-orchid)"],
               thing: ["", "var(--sm-thing)"] };
  function roleLabel(role, hub) { return role === "thing" ? (hub ? "Subject" : "Detail") : ROLE[role][0]; }

  // ------------------------------------------------------------------ the live strip
  function LivePill(p) {
    var now = p.now;
    if (!now) return h("span", { className: "sm-pill" }, h("span", { className: "sm-dot" }), "…");
    var s = now.sleep || {}, pr = s.progress || {};
    var down = (now.models || []).filter(function (m) { return !m.up; }).map(function (m) { return m.role; });
    var deg = Object.keys(now.degraded || {}).concat(down);
    var tone = "ok", text;
    if (s.running) { tone = "sleep"; text = "Asleep · " + capital(pr.step || "starting") + " · " + (pr.index || 0) + "/" + ((pr.steps || []).length || "?"); }
    else if (deg.length) { tone = "warn"; text = "Degraded: " + deg.join(", "); }
    else { text = "Awake" + (s.next && s.next.at ? " · sleeps at " + clock(s.next.at) : ""); }
    return h("button", { type: "button", className: "sm-pill sm-pill-" + tone, onClick: p.onClick, title: "What Sophia is doing now" },
      h("span", { className: "sm-dot" }), h("span", { role: "status" }, text));
  }

  function NightCell(p) {
    var s = p.sleep || {}, pr = s.progress || {}, last = s.last || {}, next = s.next || {};
    if (s.running) {
      var frac = pr.total ? Math.min(1, pr.done / pr.total) : null;
      return h("div", { className: "sm-now-cell sm-now-sleep" },
        h("div", { className: "sm-now-label" }, "The night"),
        h("div", { className: "sm-now-big" }, "Asleep · ", capital(pr.step || "starting")),
        h("div", { className: "sm-now-sub" }, "Step " + pr.index + " of " + (pr.steps || []).length + " · " + dur(Date.now() / 1000 - (pr.step_started || pr.started)) + " in this step"),
        h("div", { className: cx("sm-progress", frac == null && "sm-progress-busy") },
          h("span", { style: { width: frac == null ? "35%" : (frac * 100) + "%" } })),
        h("div", { className: "sm-now-sub sm-mono" }, (pr.total ? pr.done + " / " + pr.total + " items · " : "") + pr.calls + " model calls · started " + clock(pr.started)));
    }
    var interrupted = pr.status === "interrupted";
    return h("div", { className: "sm-now-cell" },
      h("div", { className: "sm-now-label" }, "The night"),
      h("div", { className: "sm-now-big" }, next.at ? "Next sleep " + clock(next.at) : next.scheduled ? "Scheduled " + next.schedule : "Not scheduled"),
      h("div", { className: "sm-now-sub" }, next.at ? until(next.at) : "No crontab line runs `hermes sophia sleep`."),
      interrupted ? h("div", { className: "sm-now-sub sm-warn" }, "The last run stopped during " + pr.step + ".")
        : last.night_id && h("div", { className: "sm-now-sub" }, "Last: " + (last.status || "?") + " " + ago(last.finished) + " · took " + dur(last.seconds)));
  }

  function NowStrip(p) {
    var now = p.now, go = p.go;
    if (!now) return h(Card, { title: "Right now", className: "sm-now" }, h(Loading));
    var w = now.waiting || {}, cap = now.capture;
    return h(Card, { title: "Right now", className: "sm-now", aside: h("span", { className: "sm-live" }, h("span", { className: "sm-live-dot" }), "live") },
      h("div", { className: "sm-now-grid" },
        h(NightCell, { sleep: now.sleep }),
        h("div", { className: "sm-now-cell" },
          h("div", { className: "sm-now-label" }, "Waiting for tonight"),
          h("div", { className: "sm-now-big" }, w.lines + " line" + (w.lines === 1 ? "" : "s")),
          h("div", { className: cx("sm-now-sub", w.missing_vectors && "sm-warn") },
            w.missing_vectors ? w.missing_vectors + " still need embeddings" : "all searchable already")),
        h("div", { className: "sm-now-cell" },
          h("div", { className: "sm-now-label" }, "Models"),
          h("ul", { className: "sm-models" }, (now.models || []).map(function (m) {
            var tone = !m.up ? "down" : m.busy ? "busy" : "up";
            return h("li", { key: m.role, title: m.error || m.server },
              h("span", { className: "sm-dot sm-dot-" + tone }), h("span", { className: "sm-model-role" }, m.role),
              h("span", { className: "sm-model-name" }, m.model),
              h("span", { className: "sm-model-state" }, !m.up ? "down" : m.busy ? "working" : m.ms != null ? m.ms + " ms" : "up"));
          })),
          Object.keys(now.degraded || {}).map(function (k) {
            return h("div", { key: k, className: "sm-now-sub sm-warn" }, k + " degraded " + ago(now.degraded[k].since) + ": " + trunc(now.degraded[k].why, 90));
          })),
        h("div", { className: "sm-now-cell" },
          h("div", { className: "sm-now-label" }, "Last line captured"),
          cap ? h(React.Fragment, null,
            h("div", { className: "sm-now-big" }, ago(cap.said)),
            h("div", { className: "sm-now-sub" }, who(cap.speaker) + (String(cap.flags || "").indexOf("assistant") >= 0 ? " (reply)" : "") + " · " + clock(cap.said)),
            h("div", { className: "sm-now-sub sm-mono" }, trunc(cap.session_id, 28)))
            : h("div", { className: "sm-now-sub" }, "Nothing yet"))),
      h("div", { className: "sm-feed" },
        h("div", { className: "sm-feed-head" }, h("h3", { className: "sm-h3" }, "Latest recalls"),
          h(Btn, { small: true, onClick: function () { go("recall"); } }, "All recalls")),
        (now.recall || []).length ? h("ul", { className: "sm-feed-list" }, now.recall.map(function (r) {
          return h("li", { key: r.id }, h("button", { type: "button", className: "sm-feed-row", onClick: function () { go("recall", r.id); } },
            h(VerdictChip, { verdict: r.verdict, n: r.n }),
            h("span", { className: "sm-feed-q" }, trunc(r.query, 140)),
            h("span", { className: "sm-feed-t" }, ago(r.said))));
        })) : h(Empty, null, "No messages since the store was created.")));
  }

  // ------------------------------------------------------------------ overview
  var STEP_ORDER = ["settle", "sort", "contextualize", "headroom", "relate", "integrate", "tasks", "index", "outcomes", "replay",
                    "rehearse", "calibrate", "promote", "views", "anticipate", "tidy"];
  function LastNight(p) {
    var n = p.night;
    if (!n) return h(Card, { title: "Last night" }, h(Empty, null, "No night has run yet. The first one sorts everything captured so far."));
    var steps = n.steps.filter(function (s) { return s.seconds >= 1 || s.failed; });
    var max = Math.max.apply(null, steps.map(function (s) { return s.seconds; }).concat([1]));
    var total = n.steps.reduce(function (a, s) { return a + s.seconds; }, 0);
    return h(Card, { title: "Last night", aside: h("span", { className: "sm-mono sm-muted" }, clock(n.finished) + " · " + dur(total) + " · " + n.status) },
      h("p", { className: "sm-lede" }, n.new_facts + " new facts, " + n.tasks + " task cards, " + n.superseded + " facts marked as changed, and " +
        n.plans_unconfirmed + " plans whose date passed without word."),
      n.judge_errors ? h("p", { className: "sm-warn" }, n.judge_errors + " judgments failed and were treated as “no”.") : null,
      h("ul", { className: "sm-steps" }, steps.map(function (s) {
        return h("li", { key: s.step },
          h("span", { className: "sm-step-name" }, capital(s.step)),
          h("span", { className: "sm-step-bar" }, h("span", { style: { width: (100 * s.seconds / max) + "%" }, className: s.failed ? "sm-failed-bar" : "" })),
          h("span", { className: "sm-step-t" }, s.failed ? "failed" : dur(s.seconds)));
      })));
  }

  var SPEAKER_COLORS = ["var(--sm-violet)", "var(--sm-cyan)", "var(--sm-orchid)", "var(--sm-green)", "var(--sm-amber)", "var(--sm-grey)", "var(--sm-quiet)"];
  function InMemory(p) {
    var z = p.sizes;
    var parts = z.speakers.map(function (s, i) { return { label: s[0], v: s[1], color: SPEAKER_COLORS[i % SPEAKER_COLORS.length] }; });
    return h(Card, { title: "What's in memory" },
      h("div", { className: "sm-stats" },
        [[z.lines, "lines kept verbatim"], [z.facts, "facts"], [z.entities, "people, places, things"], [z.tasks, "task cards"]].map(function (x) {
          return h("div", { key: x[1], className: "sm-stat" }, h("span", { className: "sm-stat-n" }, x[0]), h("span", { className: "sm-stat-l" }, x[1]));
        })),
      h("div", { className: "sm-sub-head" }, "Who said the lines"),
      h(Bar, { parts: parts }), h(Legend, { parts: parts }));
  }

  function RecallWeek(p) {
    var r = p.recall, v = r.verdicts || {};
    var parts = [["general", "Nothing needed"], ["injected", "Memory injected"], ["possible", "Possible matches only"],
                 ["nothing_found", "Nothing found"], ["closed", "Gate closed"], ["degraded", "Degraded"]]
      .filter(function (x) { return v[x[0]]; })
      .map(function (x) { return { label: x[1], v: v[x[0]], color: VERDICT[x[0]][1] }; });
    var allIn = r.messages > 3 && (v.injected || 0) + (v.possible || 0) === r.messages;
    return h(Card, { title: "Recall", aside: h("span", { className: "sm-muted" }, "last " + r.days + " days") },
      h("div", { className: "sm-stats" },
        h("div", { className: "sm-stat" }, h("span", { className: "sm-stat-n" }, r.messages), h("span", { className: "sm-stat-l" }, "messages")),
        h("div", { className: "sm-stat" }, h("span", { className: "sm-stat-n" }, Math.round(r.median_lines || 0)), h("span", { className: "sm-stat-l" }, "lines injected, median")),
        r.median_ms != null && h("div", { className: "sm-stat" }, h("span", { className: "sm-stat-n" }, r.median_ms), h("span", { className: "sm-stat-l" }, "ms, median"))),
      parts.length ? h(React.Fragment, null, h(Bar, { parts: parts }), h(Legend, { parts: parts })) : h(Empty, null, "No messages this week."),
      allIn ? h("p", { className: "sm-insight" }, "Every message this week got memory added. The gate hasn't turned anything away; small talk may be pulling in more than it needs.") : null);
  }

  function QueueItem(p) {
    var it = p.item, ctx = useContext(Ctx), done = p.done;
    var busy = useState(false);
    function act(req, label) {
      busy[1](true);
      req.then(function (r) {
        busy[1](false);
        p.onResolved(label, r && r.journal_id);
        ctx.changed();
      }, function (e) { busy[1](false); ctx.notify("Couldn't do that: " + errText(e)); });
    }
    function review(label) { act(post("/review", { item: it.key }), label); }
    var kind, title, detail, extra = null, actions = [];
    if (it.type === "superseded") {
      kind = ["A change that may be wrong", "var(--sm-rose)"];
      title = "“" + sentence(it.old) + "” was replaced by “" + sentence(it.new) + "”";
      detail = "The night judged the newer fact made the older one untrue" + (it.p != null ? " (" + it.p.toFixed(2) + ")" : "") + ". Undo if the two can both be true.";
      actions = [["Undo", true, function () { act(post("/undo", { journal_id: it.journal_id }).then(function () { return {}; }), "Undone · the older fact is current again"); }],
                 ["Keep", false, function () { review("Kept as changed"); }]];
    } else if (it.type === "plan") {
      kind = ["A plan with no outcome", "var(--sm-amber)"];
      title = sentence(it.fact);
      var src = (it.sources || [])[0];
      detail = (it.happens ? "Planned for " + it.happens + ". " : "") + "The date passed and nobody said whether it happened.";
      extra = src ? h("div", { className: "sm-q-src" }, h(Quote, null, trunc(src.text, 220)), h("div", { className: "sm-src" }, speakerLabel(src) + " · " + stamp(src.said))) : null;
      actions = [["It happened", true, function () { act(post("/plan", { fact_id: it.id, outcome: "happened" }), "Marked as happened"); }],
                 ["It didn’t", false, function () { act(post("/plan", { fact_id: it.id, outcome: "didnt" }), "Marked as didn’t happen"); }],
                 ["Leave", false, function () { review("Left unconfirmed"); }]];
    } else if (it.type === "recall_miss") {
      kind = ["Recall couldn't find it again", "var(--sm-cyan)"];
      title = it.question || sentence(it.fact);
      detail = "Rehearsal asked this about a stored fact (“" + sentence(it.fact) + "”) and recall missed it.";
      actions = [["Open page", false, function () { p.go("pages", (it.fact || [])[0]); }], ["Dismiss", false, function () { review("Dismissed"); }]];
    } else if (it.type === "step_failed") {
      kind = ["A night step failed", "var(--sm-rose)"];
      title = capital(it.step) + " failed";
      detail = trunc(it.error, 240) + " Its work is redone next night.";
    } else if (it.type === "degraded") {
      kind = ["Running degraded", "var(--sm-rose)"];
      title = capital(it.name) + " model unavailable";
      detail = trunc(it.why, 240) + (it.since ? " (since " + stamp(it.since) + ")" : "");
    } else {
      kind = [it.type, "var(--sm-grey)"]; title = it.key; detail = "";
    }
    if (done) {
      return h("li", { className: "sm-q sm-q-done" },
        h("div", { className: "sm-q-kind sm-ok" }, h(Icon, { name: "check", size: 16 }), done.label),
        h("div", { className: "sm-q-title-done" }, trunc(title, 140)),
        done.journal_id ? h("div", { className: "sm-q-actions" }, h(Btn, { small: true, onClick: function () {
          ctx.undo(done.journal_id, p.onUndone);
        } }, "Undo")) : null);
    }
    return h("li", { className: "sm-q" },
      h("div", { className: "sm-q-kind" }, h("span", { className: "sm-dot", style: { background: kind[1] } }), kind[0]),
      h("div", { className: "sm-q-title" }, title),
      detail && h("div", { className: "sm-q-detail" }, detail),
      extra,
      actions.length ? h("div", { className: "sm-q-actions" }, actions.map(function (a) {
        return h(Btn, { key: a[0], primary: a[1], onClick: a[2], disabled: busy[0] }, a[0]);
      })) : null);
  }

  function Queue(p) {
    var all = useState(false);
    var q = useApi("/queue" + (all[0] ? "?plans=200" : ""), 30000);
    var ctx = useContext(Ctx);
    useEffect(function () { q.reload(); }, [ctx.version]);   // eslint-disable-line
    // items someone just resolved stay where they were (showing their Undo) until the page is left
    var resS = useState({}), resolved = resS[0];
    var fresh = (q.data && q.data.items) || [];
    var items = fresh.slice();
    Object.keys(resolved).forEach(function (k) {
      if (!fresh.some(function (i) { return i.key === k; })) items.splice(Math.min(resolved[k].at, items.length), 0, resolved[k].item);
    });
    var open = items.filter(function (i) { return !resolved[i.key]; });
    var plansShown = fresh.filter(function (i) { return i.type === "plan"; }).length;
    var more = q.data ? q.data.plans_total - plansShown : 0;
    function resolve(it, at) {
      return function (label, jid) { resS[1](function (r) { var n = Object.assign({}, r); n[it.key] = { item: it, at: at, label: label, journal_id: jid }; return n; }); };
    }
    function unresolve(it) {
      return function () { resS[1](function (r) { var n = Object.assign({}, r); delete n[it.key]; return n; }); };
    }
    return h(Card, { title: "Needs a look", count: q.data ? open.length + Math.max(0, more) : null, className: "sm-span2" },
      q.error && !q.data ? h(Failed, { error: q.error, retry: q.reload }) : !q.data ? h(Loading) :
      items.length ? h(React.Fragment, null,
        h("ul", { className: "sm-queue" }, items.map(function (it, i) {
          return h(QueueItem, { key: it.key, item: it, go: p.go, done: resolved[it.key] || null, onResolved: resolve(it, i), onUndone: unresolve(it) });
        })),
        more > 0 ? h("div", { className: "sm-more" }, h(Btn, { onClick: function () { all[1](true); } }, "Show " + more + " more plans")) : null)
      : h(Empty, null, "Nothing waiting. Changes the night makes on thin evidence, and plans whose date passes without word, land here."));
  }

  function journalLine(e) {
    var d = e.detail || {};
    switch (e.kind) {
      case "superseded": return ["“" + sentence(d.old) + "” → “" + sentence(d.new) + "”", d.p != null ? d.p.toFixed(2) : ""];
      case "plan_unconfirmed": return ["Date passed, unconfirmed: " + sentence(d), ""];
      case "speaker_corrected": return [d.windows + " lines relabelled " + d.from + " → " + d.to, d.reason];
      case "windows_dropped": return [d.windows + " lines kept out of recall", d.reason];
      case "fact_retracted": return ["Retracted “" + sentence(d.fact) + "”", d.reason];
      case "plan_resolved": return ["“" + sentence(d.fact) + "” " + (d.outcome === "happened" ? "happened" : "didn’t happen"), d.reason];
      case "reviewed": return ["Looked at and left as it is", d.item];
      case "undone": return ["Undid change #" + d.journal_id, ""];
      case "canonical_relation": return ["“" + (d.relation || "(empty)") + "” became a known relation", d.instances + " uses"];
      case "task_succeeded": return ["Task card: " + d.goal, d.steps + " steps"];
      case "recall_miss": return ["Recall missed: " + d.question, ""];
      case "failed": return ["Step " + e.step + " failed", trunc((d && d.error) || "", 120)];
      case "yielded": return ["The night yielded", String(e.detail)];
      default: return [e.kind.replace(/_/g, " "), typeof d === "string" ? d : ""];
    }
  }

  function Changes(p) {
    var j = useApi("/journal?limit=80", 30000);
    var ctx = useContext(Ctx);
    useEffect(function () { j.reload(); }, [ctx.version]);   // eslint-disable-line
    var rows = useMemo(function () {
      if (!j.data) return [];
      var out = [], plans = {};
      j.data.entries.forEach(function (e) {
        if (e.kind === "plan_unconfirmed") {
          if (!plans[e.night_id]) { plans[e.night_id] = { id: "plans-" + e.night_id, group: true, night_id: e.night_id, n: 0 }; out.push(plans[e.night_id]); }
          plans[e.night_id].n++;
        } else if (e.kind !== "reviewed") out.push(e);
      });
      return out.slice(0, 24);
    }, [j.data]);
    return h(Card, { title: "Recent changes", aside: h("span", { className: "sm-muted" }, "journaled · undoable") },
      j.error && !j.data ? h(Failed, { error: j.error, retry: j.reload }) : !j.data ? h(Loading) :
      rows.length ? h("ul", { className: "sm-changes" }, rows.map(function (e) {
        if (e.group) return h("li", { key: e.id }, h("div", { className: "sm-ch-main" },
          h("div", { className: "sm-ch-text" }, e.n + " plans had their date pass without word"),
          h("div", { className: "sm-ch-meta" }, nightDate(e.night_id) + " · listed under Needs a look")));
        var line = journalLine(e);
        return h("li", { key: e.id, className: e.undone ? "sm-ch-undone" : "" },
          h("div", { className: "sm-ch-main" },
            h("div", { className: "sm-ch-text" }, line[0]),
            h("div", { className: "sm-ch-meta" }, nightDate(e.night_id) + (line[1] ? " · " + trunc(String(line[1]), 120) : ""))),
          e.undone ? h("span", { className: "sm-tag" }, "undone")
            : e.undoable ? h(Btn, { small: true, onClick: function () { ctx.undo(e.id); } }, "Undo") : null);
      })) : h(Empty, null, "No changes yet."));
  }

  function Overview(p) {
    var ov = useApi("/overview", 30000);
    var ctx = useContext(Ctx);
    useEffect(function () { ov.reload(); }, [ctx.version]);   // eslint-disable-line
    var d = ov.data;
    return h("div", { className: "sm-overview" },
      h(NowStrip, { now: p.now, go: p.go }),
      ov.error && !d ? h(Failed, { error: ov.error, retry: ov.reload }) : !d ? h(Loading) :
      h("div", { className: "sm-grid3" }, h(LastNight, { night: d.night }), h(InMemory, { sizes: d.sizes }), h(RecallWeek, { recall: d.recall })),
      h("div", { className: "sm-grid3" }, h(Queue, { go: p.go }), h(Changes, null)));
  }

  // ------------------------------------------------------------------ graph
  var EDGE = {
    now: { color: "var(--sm-edge)", dash: "" },
    planned: { color: "var(--sm-amber)", dash: "2 5" },
    check: { color: "var(--sm-amber)", dash: "2 5" },
    before: { color: "var(--sm-grey)", dash: "7 6" }
  };

  function radius(n) { return n.subject ? Math.min(30, 7 + 2.6 * Math.sqrt(n.facts)) : Math.min(12, 4 + Math.sqrt(n.facts)); }

  // A small force layout: settled nodes keep their place (they move a little), new nodes start beside a neighbour.
  function settle(vis, links, pos, iters) {
    var n = vis.length, P = new Array(n), idx = {};
    vis.forEach(function (v, i) { idx[v.id] = i; });
    var fresh = 0;
    vis.forEach(function (v, i) {
      var p = pos[v.id];
      if (!p) {
        var near = null;
        for (var k = 0; k < links.length && !near; k++) {
          var l = links[k];
          if (l.a === v.id && pos[l.b]) near = pos[l.b];
          else if (l.b === v.id && pos[l.a]) near = pos[l.a];
        }
        var ang = Math.random() * Math.PI * 2, dist = near ? 30 + Math.random() * 30 : 40 + Math.random() * 120;
        p = pos[v.id] = { x: (near ? near.x : 0) + Math.cos(ang) * dist, y: (near ? near.y : 0) + Math.sin(ang) * dist, fresh: true };
        fresh++;
      }
      P[i] = p;
    });
    if (!fresh && iters < 100) return;
    var R = vis.map(radius), L = links.map(function (l) { return [idx[l.a], idx[l.b], l.len, l.k]; })
      .filter(function (l) { return l[0] != null && l[1] != null; });
    var dx = new Float64Array(n), dy = new Float64Array(n);
    for (var it = 0; it < iters; it++) {
      var temp = 1 + 24 * (1 - it / iters);
      dx.fill(0); dy.fill(0);
      for (var i = 0; i < n; i++) {
        for (var j = i + 1; j < n; j++) {
          var ex = P[i].x - P[j].x, ey = P[i].y - P[j].y, d2 = ex * ex + ey * ey + 0.01;
          if (d2 > 40000) continue;                          // only neighbours push
          var d = Math.sqrt(d2), gap = R[i] + R[j] + 10;
          var f = 400 / d2 + (d < gap ? (gap - d) * 0.5 / d : 0);
          dx[i] += ex * f; dy[i] += ey * f; dx[j] -= ex * f; dy[j] -= ey * f;
        }
      }
      for (var m = 0; m < L.length; m++) {
        var a = L[m][0], b = L[m][1], lx = P[b].x - P[a].x, ly = P[b].y - P[a].y, dl = Math.sqrt(lx * lx + ly * ly) + 0.01;
        var s = (dl - L[m][2]) * L[m][3] / dl;
        dx[a] += lx * s; dy[a] += ly * s; dx[b] -= lx * s; dy[b] -= ly * s;
      }
      for (var q = 0; q < n; q++) {
        dx[q] -= P[q].x * 0.03; dy[q] -= P[q].y * 0.03;
        var lim = P[q].fresh ? temp : temp * 0.3, mag = Math.sqrt(dx[q] * dx[q] + dy[q] * dy[q]);
        if (mag > lim) { dx[q] *= lim / mag; dy[q] *= lim / mag; }
        P[q].x += dx[q]; P[q].y += dy[q];
      }
    }
    P.forEach(function (p) { p.fresh = false; });
  }

  function GraphView(p) {
    var g = useApi("/graph", 0);
    var ctx = useContext(Ctx);
    useEffect(function () { g.reload(); }, [ctx.version]);   // eslint-disable-line
    var wide = p.wide;
    var selS = useState(p.arg || null), sel = selS[0], setSel = selS[1];
    var expS = useState(function () { return p.arg ? [p.arg] : []; }), expanded = expS[0], setExpanded = expS[1];
    var showS = useState({ now: true, planned: true, check: true, before: true }), show = showS[0], setShow = showS[1];
    var allS = useState(false), showAll = allS[0];
    var togS = useState(true), together = togS[0];
    var qS = useState(""), query = qS[0];
    var sheetS = useState(false), sheetOpen = sheetS[0];
    var pos = useRef({});
    var viewS = useState({ k: 1, x: 0, y: 0 }), view = viewS[0], setView = viewS[1];
    var boxRef = useRef(null), svgRef = useRef(null);
    var sizeS = useState({ w: 0, h: 0 }), size = sizeS[0];
    var fitted = useRef(false);

    useEffect(function () { if (p.arg) { setSel(p.arg); setExpanded(function (e) { return e.indexOf(p.arg) >= 0 ? e : e.concat([p.arg]); }); } }, [p.arg]);

    useEffect(function () {
      var el = boxRef.current;
      if (!el) return undefined;
      var ro = new ResizeObserver(function () { sizeS[1]({ w: el.clientWidth, h: el.clientHeight }); });
      ro.observe(el);
      return function () { ro.disconnect(); };
    }, [g.data]);

    var data = g.data;
    var byId = useMemo(function () {
      var m = {};
      (data ? data.nodes : []).forEach(function (n) { m[n.id] = n; });
      return m;
    }, [data]);

    var shown = useMemo(function () {
      if (!data) return { nodes: [], edges: [], links: [], ties: [] };
      var exp = {};
      expanded.forEach(function (x) { exp[x] = true; });
      var edges = data.edges.filter(function (e) {
        if (!show[statusGroup(e)]) return false;
        var hubPair = byId[e.s] && byId[e.s].subject && byId[e.o] && byId[e.o].subject;
        return showAll || hubPair || exp[e.s] || exp[e.o];
      });
      var ids = {};
      data.nodes.forEach(function (n) { if (n.subject) ids[n.id] = true; });
      edges.forEach(function (e) { ids[e.s] = true; ids[e.o] = true; });
      var nodes = data.nodes.filter(function (n) { return ids[n.id]; });
      var ties = together ? data.together.filter(function (t) { return ids[t.a] && ids[t.b]; }) : [];
      var seen = {}, links = [];
      edges.forEach(function (e) {
        var key = e.s < e.o ? e.s + "|" + e.o : e.o + "|" + e.s;
        if (seen[key]) return;
        seen[key] = true;
        var hub = byId[e.s].subject && byId[e.o].subject;
        links.push({ a: e.s, b: e.o, len: hub ? 110 : 30 + radius(byId[e.s]) + radius(byId[e.o]), k: hub ? 0.02 : 0.08 });
      });
      ties.forEach(function (t) { links.push({ a: t.a, b: t.b, len: 220, k: 0.004 * Math.min(t.n, 5) }); });
      return { nodes: nodes, edges: edges, links: links, ties: ties };
    }, [data, byId, expanded, show, showAll, together]);

    var laid = useMemo(function () {
      if (!shown.nodes.length) return 0;
      settle(shown.nodes, shown.links, pos.current, shown.nodes.length > 150 ? 140 : 220);
      return Date.now();
    }, [shown]);

    var fitTo = useCallback(function (ids, maxK) {
      if (!ids.length || !size.w) return;
      var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      ids.forEach(function (id) {
        var q = pos.current[id];
        if (!q) return;
        x0 = Math.min(x0, q.x); y0 = Math.min(y0, q.y); x1 = Math.max(x1, q.x); y1 = Math.max(y1, q.y);
      });
      if (x0 === Infinity) return;
      var hh = wide ? size.h : Math.max(180, size.h - 170);   // phones: keep it above the folded panel
      var m = 60, k = Math.min((size.w - 2 * m) / Math.max(1, x1 - x0), (hh - 2 * m) / Math.max(1, y1 - y0));
      k = Math.max(0.15, Math.min(maxK || 2.2, k));
      setView({ k: k, x: size.w / 2 - k * (x0 + x1) / 2, y: hh / 2 - k * (y0 + y1) / 2 });
    }, [size, wide]);
    var focus = useRef(null);
    useEffect(function () {
      var id = focus.current;
      if (!id || !laid) return;
      focus.current = null;
      var ids = [id];
      shown.edges.forEach(function (e) { if (e.s === id) ids.push(e.o); else if (e.o === id) ids.push(e.s); });
      fitTo(ids, 1.6);
    }, [laid, sel, fitTo]);   // eslint-disable-line

    var fit = useCallback(function () {
      var ns = shown.nodes;
      if (!ns.length) return;
      var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      ns.forEach(function (n) {
        var q = pos.current[n.id];
        if (!q) return;
        x0 = Math.min(x0, q.x); y0 = Math.min(y0, q.y); x1 = Math.max(x1, q.x); y1 = Math.max(y1, q.y);
      });
      var m = 60, k = Math.min((size.w - 2 * m) / Math.max(1, x1 - x0), (size.h - 2 * m) / Math.max(1, y1 - y0));
      k = Math.max(0.15, Math.min(2.2, k));
      setView({ k: k, x: size.w / 2 - k * (x0 + x1) / 2, y: size.h / 2 - k * (y0 + y1) / 2 });
    }, [shown, size]);

    useEffect(function () { if (laid && size.w > 0 && !fitted.current) { fitted.current = true; fit(); } }, [laid, size, fit]);

    // pan (drag), zoom (wheel, pinch), tap to select
    var ptrs = useRef({}), gesture = useRef(null);
    function toLocal(e) {
      var r = svgRef.current.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }
    function zoomAt(pt, factor) {
      setView(function (v) {
        var k = Math.max(0.12, Math.min(4, v.k * factor)), f = k / v.k;
        return { k: k, x: pt.x - (pt.x - v.x) * f, y: pt.y - (pt.y - v.y) * f };
      });
    }
    useEffect(function () {
      var el = svgRef.current;
      if (!el) return undefined;
      var onWheel = function (e) { e.preventDefault(); zoomAt(toLocal(e), Math.exp(-e.deltaY * 0.0015)); };
      el.addEventListener("wheel", onWheel, { passive: false });
      return function () { el.removeEventListener("wheel", onWheel); };
    }, [g.data]);
    function onDown(e) {
      var pt = toLocal(e);
      ptrs.current[e.pointerId] = pt;
      try { svgRef.current.setPointerCapture(e.pointerId); } catch (x) { /* ignore */ }
      var ids = Object.keys(ptrs.current);
      if (ids.length === 1) {
        var hit = e.target.closest && e.target.closest("[data-node]");
        gesture.current = { type: "pan", start: pt, view: view, moved: false, node: hit ? hit.getAttribute("data-node") : null };
      } else if (ids.length === 2) {
        var a = ptrs.current[ids[0]], b = ptrs.current[ids[1]];
        gesture.current = { type: "pinch", d: Math.hypot(a.x - b.x, a.y - b.y), mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, view: view, moved: true };
      }
    }
    function onMove(e) {
      if (!ptrs.current[e.pointerId] || !gesture.current) return;
      var pt = toLocal(e);
      ptrs.current[e.pointerId] = pt;
      var gs = gesture.current;
      if (gs.type === "pan") {
        var ddx = pt.x - gs.start.x, ddy = pt.y - gs.start.y;
        if (!gs.moved && Math.hypot(ddx, ddy) < 5) return;
        gs.moved = true;
        setView({ k: gs.view.k, x: gs.view.x + ddx, y: gs.view.y + ddy });
      } else {
        var ids = Object.keys(ptrs.current);
        if (ids.length < 2) return;
        var a = ptrs.current[ids[0]], b = ptrs.current[ids[1]], d = Math.hypot(a.x - b.x, a.y - b.y);
        var k = Math.max(0.12, Math.min(4, gs.view.k * d / gs.d)), f = k / gs.view.k;
        setView({ k: k, x: gs.mid.x - (gs.mid.x - gs.view.x) * f, y: gs.mid.y - (gs.mid.y - gs.view.y) * f });
      }
    }
    function onUp(e) {
      var gs = gesture.current;
      delete ptrs.current[e.pointerId];
      if (gs && gs.type === "pan" && !gs.moved) {
        if (gs.node) pick(gs.node); else setSel(null);
      }
      if (!Object.keys(ptrs.current).length) gesture.current = null;
    }
    function pick(id) {
      var n = byId[id];
      if (!n) return;
      if (sel === id && n.subject) {
        setExpanded(function (e) { return e.indexOf(id) >= 0 ? e.filter(function (x) { return x !== id; }) : e.concat([id]); });
        return;
      }
      if (sel !== id) sheetS[1](false);               // phones: the panel opens folded so the graph stays in view
      setSel(id);
      if (n.subject) {
        focus.current = id;
        setExpanded(function (e) { return e.indexOf(id) >= 0 ? e : e.concat([id]); });
      }
    }
    function find(e) {
      e.preventDefault();
      var q = query.trim().toLowerCase();
      if (!q || !data) return;
      var hit = data.nodes.filter(function (n) { return n.label.toLowerCase().indexOf(q) >= 0; })
        .sort(function (a, b) { return (b.subject - a.subject) || (b.facts - a.facts); })[0];
      if (!hit) { ctx.notify("Nothing in the graph matches “" + query + "”."); return; }
      if (!hit.subject) {
        var owner = data.edges.filter(function (x) { return x.o === hit.id || x.s === hit.id; })[0];
        if (owner) setExpanded(function (ex) { var o = owner.s === hit.id ? owner.o : owner.s; return ex.indexOf(o) >= 0 ? ex : ex.concat([o]); });
      }
      setSel(hit.id);
      setTimeout(function () {
        var q2 = pos.current[hit.id];
        if (q2) setView(function (v) { var k = Math.max(v.k, 1.1); return { k: k, x: size.w / 2 - k * q2.x, y: size.h / 2 - k * q2.y }; });
      }, 30);
    }

    if (g.error && !data) return h(Failed, { error: g.error, retry: g.reload });
    if (!data) return h(Loading);

    var near = {};
    if (sel) {
      near[sel] = true;
      shown.edges.forEach(function (e) { if (e.s === sel) near[e.o] = true; if (e.o === sel) near[e.s] = true; });
    }
    var selEdges = sel ? shown.edges.filter(function (e) { return e.s === sel || e.o === sel; }) : [];
    var labelAll = view.k >= 1.25;

    var svg = h("svg", { ref: svgRef, className: "sm-svg", width: size.w, height: size.h, role: "img",
        "aria-label": "Memory graph: " + shown.nodes.length + " entities, " + shown.edges.length + " facts shown",
        onPointerDown: onDown, onPointerMove: onMove, onPointerUp: onUp, onPointerCancel: onUp },
      h("g", { transform: "translate(" + view.x + "," + view.y + ") scale(" + view.k + ")" },
        shown.ties.map(function (t) {
          var a = pos.current[t.a], b = pos.current[t.b];
          if (!a || !b) return null;
          return h("line", { key: "t" + t.a + t.b, x1: a.x, y1: a.y, x2: b.x, y2: b.y, className: "sm-tie", strokeWidth: Math.min(4, 0.6 + t.n * 0.4) / view.k });
        }),
        shown.edges.map(function (e) {
          var a = pos.current[e.s], b = pos.current[e.o];
          if (!a || !b) return null;
          var st = EDGE[statusGroup(e)], lit = sel && (e.s === sel || e.o === sel);
          return h("line", { key: e.id, x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: st.color, strokeDasharray: st.dash,
            strokeWidth: (lit ? 2.2 : 1.3) / Math.sqrt(view.k), opacity: sel ? (lit ? 1 : 0.18) : 0.6 });
        }),
        selEdges.length <= 12 ? selEdges.map(function (e) {
          var a = pos.current[e.s], b = pos.current[e.o];
          if (!a || !b || Math.hypot(a.x - b.x, a.y - b.y) * view.k < 120) return null;
          return h("text", { key: "l" + e.id, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, className: "sm-edge-label",
            fontSize: 11 / view.k, textAnchor: "middle" }, trunc(e.relation, 34));
        }) : null,
        shown.nodes.map(function (n) {
          var q = pos.current[n.id];
          if (!q) return null;
          var r = radius(n), on = n.id === sel, dim = sel && !near[n.id], col = ROLE[n.role][1];
          var showLabel = n.subject || on || (sel && near[n.id]) || labelAll;
          return h("g", { key: n.id, "data-node": n.id, className: cx("sm-node", dim && "sm-dim"), transform: "translate(" + q.x + "," + q.y + ")" },
            h("circle", { r: Math.max(r, (wide ? 10 : 22) / view.k), fill: "transparent" }),
            on && h("circle", { r: r + 6, className: "sm-halo" }),
            h("circle", { r: Math.max(r, 3.5 / view.k), fill: col, fillOpacity: n.subject ? 0.22 : 0.14, stroke: col, strokeWidth: (on ? 2.5 : 1.5) / view.k }),
            showLabel && h("text", { y: r + 13 / view.k, className: cx("sm-node-label", n.subject && "sm-node-hub"), fontSize: (n.subject ? 12.5 : 11) / view.k,
              textAnchor: "middle" }, trunc(n.label, n.subject ? 26 : 30)));
        })));

    var selNode = sel ? byId[sel] : null;
    var detail = selNode ? h(GraphDetail, { node: selNode, edges: selEdges.length ? selEdges : data.edges.filter(function (e) { return e.s === sel || e.o === sel; }),
      byId: byId, expanded: expanded.indexOf(sel) >= 0, go: p.go, pick: pick,
      toggle: function () { setExpanded(function (e) { return e.indexOf(sel) >= 0 ? e.filter(function (x) { return x !== sel; }) : e.concat([sel]); }); },
      close: function () { setSel(null); } }) : null;

    var toolbar = h("div", { className: "sm-graph-tools" },
      h(IconBtn, { icon: "plus", label: "Zoom in", onClick: function () { zoomAt({ x: size.w / 2, y: size.h / 2 }, 1.3); } }),
      h(IconBtn, { icon: "minus", label: "Zoom out", onClick: function () { zoomAt({ x: size.w / 2, y: size.h / 2 }, 1 / 1.3); } }),
      h(IconBtn, { icon: "fit", label: "Fit to screen", onClick: fit }));

    var filters = [["now", "Current", "solid"], ["planned", "Planned", "dotted"], ["check", "Date passed", "dotted"], ["before", "Changed or cancelled", "dashed"]];
    var counts = {};
    data.edges.forEach(function (e) { var k = statusGroup(e); counts[k] = (counts[k] || 0) + 1; });
    var filterEls = filters.map(function (f) {
      var on = show[f[0]];
      return h("button", { key: f[0], type: "button", className: cx("sm-toggle", on && "sm-on"), "aria-pressed": on,
        onClick: function () { setShow(function (s) { var n = Object.assign({}, s); n[f[0]] = !s[f[0]]; return n; }); } },
        h("span", { className: "sm-line sm-line-" + f[0] }), h("span", null, f[1]), h("span", { className: "sm-toggle-n" }, counts[f[0]] || 0));
    });
    var search = h("form", { className: "sm-search", onSubmit: find, role: "search" },
      h(Icon, { name: "search", size: 18 }),
      h("input", { type: "search", value: query, placeholder: "Find a person, place, thing…", "aria-label": "Find in the graph",
        onChange: function (e) { qS[1](e.target.value); } }));
    var extras = h("div", { className: "sm-graph-extras" },
      h("label", { className: "sm-check" }, h("input", { type: "checkbox", checked: showAll, onChange: function (e) { allS[1](e.target.checked); } }), "Every fact (" + data.edges.length + ")"),
      h("label", { className: "sm-check" }, h("input", { type: "checkbox", checked: together, onChange: function (e) { togS[1](e.target.checked); } }), "Faint lines: mentioned together"),
      expanded.length ? h(Btn, { small: true, onClick: function () { setExpanded([]); } }, "Fold everything") : null);

    if (wide) {
      return h("div", { className: "sm-graph sm-graph-wide" },
        h("aside", { className: "sm-graph-side", "aria-label": "Filters" },
          search,
          h("div", { className: "sm-sub-head" }, "Show"), h("div", { className: "sm-toggles" }, filterEls),
          extras,
          h("p", { className: "sm-hint" }, "Big circles are subjects: the people and things facts are about. Click one to spread out its facts; click again to fold them. Drag to move around, scroll to zoom.")),
        h("div", { className: "sm-graph-canvas", ref: boxRef }, svg, toolbar),
        h("aside", { className: "sm-graph-detail", "aria-label": "Selected" }, detail || h(Empty, null, "Select a circle to see what memory holds about it.")));
    }
    return h("div", { className: "sm-graph sm-graph-narrow" },
      search,
      h("div", { className: "sm-chips-row" }, filterEls),
      h("div", { className: "sm-graph-canvas", ref: boxRef }, svg, toolbar),
      extras,
      detail && h("section", { className: cx("sm-sheet", !sheetOpen && "sm-sheet-folded"), "aria-label": "Selected" },
        h("button", { type: "button", className: "sm-sheet-handle", "aria-label": sheetOpen ? "Fold the panel" : "Open the panel",
          onClick: function () { sheetS[1](!sheetOpen); } }, h("span", null)),
        detail));
  }

  function GraphDetail(p) {
    var n = p.node, groups = { now: [], planned: [], check: [], before: [] };
    p.edges.forEach(function (e) { groups[statusGroup(e)].push(e); });
    var order = ["check", "now", "planned", "before"];
    return h("div", { className: "sm-gd" },
      h("div", { className: "sm-gd-kind" }, h("span", { className: "sm-dot", style: { background: ROLE[n.role][1] } }), roleLabel(n.role, n.subject) + " · " + n.facts + " fact" + (n.facts === 1 ? "" : "s")),
      h("h2", { className: "sm-gd-title" }, n.label),
      h("div", { className: "sm-gd-actions" },
        n.entity && h(Btn, { primary: true, onClick: function () { p.go("pages", n.id); } }, "Open page"),
        n.subject && h(Btn, { onClick: p.toggle }, p.expanded ? "Fold its facts" : "Spread its facts"),
        h(IconBtn, { icon: "close", label: "Clear selection", onClick: p.close, className: "sm-gd-close" })),
      h("ul", { className: "sm-gd-facts" }, order.reduce(function (acc, k) {
        return acc.concat(groups[k].slice(0, 60).map(function (e) {
          var other = e.s === n.id ? e.o : e.s, o = p.byId[other];
          return h("li", { key: e.id },
            h(Badge, { group: k }),
            h("span", { className: "sm-gd-fact" },
              e.s === n.id ? null : h("button", { type: "button", className: "sm-link", onClick: function () { p.pick(other); } }, o ? o.label : other),
              e.s === n.id ? null : " ",
              h("span", { className: "sm-rel" }, e.relation), " ",
              e.s === n.id ? h("button", { type: "button", className: "sm-link", onClick: function () { p.pick(other); } }, o ? o.label : other) : h("span", { className: "sm-muted" }, "(this)"),
              e.happens ? h("span", { className: "sm-muted" }, " · " + e.happens) : null));
        }));
      }, [])));
  }

  // ------------------------------------------------------------------ pages
  function PagesIndex(p) {
    var qS = useState(""), q = qS[0];
    var list = useApi("/entities", 0);
    var ents = (list.data && list.data.entities) || [];
    var ql = q.trim().toLowerCase();
    var match = function (e) { return !ql || e.name.toLowerCase().indexOf(ql) >= 0; };
    var groups = [
      ["People who speak", ents.filter(function (e) { return e.role !== "thing" && match(e); })],
      ["What facts are about", ents.filter(function (e) { return e.role === "thing" && e.hub && match(e); })],
      ["Everything else", ents.filter(function (e) { return e.role === "thing" && !e.hub && match(e); }).slice(0, ql ? 200 : 40)]
    ];
    return h("nav", { className: "sm-index", "aria-label": "Pages" },
      h("div", { className: "sm-search" }, h(Icon, { name: "search", size: 18 }),
        h("input", { type: "search", value: q, placeholder: "Find a page…", "aria-label": "Find a page", onChange: function (e) { qS[1](e.target.value); } })),
      list.error && !list.data ? h(Failed, { error: list.error, retry: list.reload }) : !list.data ? h(Loading) :
      groups.map(function (g) {
        if (!g[1].length) return null;
        return h("div", { key: g[0], className: "sm-index-group" },
          h("div", { className: "sm-sub-head" }, g[0]),
          h("ul", null, g[1].map(function (e) {
            return h("li", { key: e.id }, h("button", { type: "button", className: cx("sm-index-item", e.id === p.current && "sm-on"),
              "aria-current": e.id === p.current ? "page" : undefined, onClick: function () { p.go("pages", e.id); } },
              h("span", { className: "sm-dot", style: { background: ROLE[e.role][1] } }), h("span", { className: "sm-index-name" }, e.name),
              h("span", { className: "sm-index-n" }, e.facts)));
          })));
      }),
      list.data && !ql && ents.length > 40 ? h("p", { className: "sm-hint" }, "Search to find the other " + (ents.length - 40) + ".") : null);
  }

  function FactCard(p) {
    var f = p.fact, src = (f.sources || [])[0], ctx = useContext(Ctx);
    var group = statusGroup(f);
    function plan(outcome, label) {
      post("/plan", { fact_id: f.id, outcome: outcome }).then(function (r) { ctx.notify(label, r.journal_id); ctx.changed(); },
        function (e) { ctx.notify("Couldn't do that: " + errText(e)); });
    }
    return h("div", { className: "sm-fact" },
      h("div", { className: "sm-fact-head" },
        h(Badge, { group: group }),
        h("div", { className: "sm-fact-text" }, sentence(f.fact), f.happens ? h("span", { className: "sm-muted" }, " · " + f.happens) : null),
        h(IconBtn, { icon: "more", label: "Correct this fact", onClick: function () { ctx.correct({ fact: f, window: src }); } })),
      src && h(Quote, null, trunc(src.text, 520)),
      src && h("div", { className: "sm-src" }, speakerLabel(src) + " · " + stamp(src.said) + (f.sources.length > 1 ? " · and " + (f.sources.length - 1) + " more" : "")),
      group === "check" && h("div", { className: "sm-q-actions" },
        h(Btn, { primary: true, onClick: function () { plan("happened", "Marked as happened"); } }, "It happened"),
        h(Btn, { onClick: function () { plan("didnt", "Marked as didn’t happen"); } }, "It didn’t")));
  }

  function who(speaker) {
    var s = speaker || "";
    if (s === "memory:memory" || s === "note") return "Memory note";
    if (s === "memory:user") return "Memory note about the user";
    if (s.indexOf("source:") === 0) return "Web · " + s.slice(7);
    if (s === "tool") return "Tool output";
    if (s === "action") return "Tool step";
    return s;
  }
  function speakerLabel(w) {
    var f = w.flags || [];
    if (f.indexOf("assistant") >= 0) return who(w.speaker) + " · reply, weaker";
    return who(w.speaker);
  }
  function FlagTags(p) {
    var f = p.flags || [], out = [];
    if (f.indexOf("dropped") >= 0) out.push("kept out of recall");
    if (f.indexOf("compacted") >= 0) out.push("compacted");
    if (f.indexOf("external") >= 0) out.push("web");
    if (f.indexOf("ungrounded") >= 0) out.push("ungrounded");
    return out.length ? h("span", { className: "sm-tags" }, out.map(function (t) { return h("span", { key: t, className: "sm-tag" }, t); })) : null;
  }

  function EntityPage(p) {
    var page = useApi("/entity/" + encodeURIComponent(p.id), 0);
    var ctx = useContext(Ctx);
    useEffect(function () { page.reload(); }, [ctx.version]);   // eslint-disable-line
    var d = page.data;
    if (page.error && !d) return h(Failed, { error: page.error, retry: page.reload });
    if (!d) return h(Loading);
    var G = d.groups;
    var sections = [["check", "Date passed, no word", "Plans whose date is behind us. Say how they went and recall stops calling them unconfirmed."],
                    ["now", "Believed now", null], ["planned", "Planned", null], ["before", "Before", "Replaced, cancelled or retracted. Kept, and recalled only as history."]];
    return h("article", { className: "sm-page" },
      !p.wide && h("button", { type: "button", className: "sm-back", onClick: function () { p.go("pages"); } }, h(Icon, { name: "back" }), "All pages"),
      h("header", { className: "sm-page-head" },
        h("div", null,
          h("h2", { className: "sm-page-title" }, d.name),
          h("div", { className: "sm-page-meta" }, [roleLabel(d.role, true), d.fact_count + " facts", d.mentions.length + (d.mentions.length >= 60 ? "+" : "") + " mentions",
            d.page_built ? "page built " + nightDate(d.page_built) : null].filter(Boolean).join(" · "))),
        h(Btn, { onClick: function () { p.go("graph", d.id); } }, "Show in graph")),
      h("div", { className: "sm-page-body" },
        h("div", { className: "sm-page-main" },
          sections.map(function (s) {
            if (!G[s[0]].length) return null;
            return h("section", { key: s[0], className: "sm-page-sec" },
              h("h3", { className: "sm-h3" }, s[1], h("span", { className: "sm-count" }, G[s[0]].length)),
              s[2] && h("p", { className: "sm-hint" }, s[2]),
              G[s[0]].map(function (f) { return h(FactCard, { key: f.id, fact: f }); }));
          }),
          h("section", { className: "sm-page-sec" },
            h("h3", { className: "sm-h3" }, "Every mention"),
            d.mentions.length ? h("ul", { className: "sm-mentions" }, d.mentions.map(function (w) {
              return h("li", { key: w.id },
                h("div", { className: "sm-mention-meta" },
                  h("span", { className: cx("sm-who", (w.flags || []).indexOf("assistant") >= 0 && "sm-who-reply") }, speakerLabel(w)),
                  h("span", { className: "sm-mono sm-muted" }, stamp(w.said)), h(FlagTags, { flags: w.flags }),
                  h(IconBtn, { icon: "more", label: "Correct this line", size: 18, className: "sm-mention-more", onClick: function () { ctx.correct({ window: w }); } })),
                h("div", { className: "sm-mention-text" }, w.text, w.cut ? "…" : ""));
            })) : h(Empty, null, "No line names it directly."))),
        h("aside", { className: "sm-page-side" },
          d.linked.length ? h("section", { className: "sm-page-sec" },
            h("h3", { className: "sm-h3" }, "Linked"),
            h("ul", { className: "sm-linked" }, d.linked.map(function (l, i) {
              var inner = [h("span", { key: "n", className: "sm-linked-name" }, l.name), h("span", { key: "r", className: "sm-muted" }, trunc(l.relation, 40))];
              return h("li", { key: l.id + i }, l.entity ? h("button", { type: "button", className: "sm-linked-item", onClick: function () { p.go("pages", l.id); } }, inner)
                : h("div", { className: "sm-linked-item sm-linked-plain" }, inner));
            }))) : null,
          h("section", { className: "sm-card sm-fixbox" },
            h("h3", { className: "sm-h3" }, "Something wrong here?"),
            h("p", { className: "sm-hint" }, "Use “…” on a fact or a line. Corrections change what was derived, never the words. Each is journaled with its reason and can be undone.")))));
  }

  function PagesView(p) {
    if (!p.wide) return p.arg ? h(EntityPage, { id: p.arg, go: p.go, wide: false }) : h(PagesIndex, { go: p.go });
    return h("div", { className: "sm-pages" },
      h("aside", { className: "sm-pages-side" }, h(PagesIndex, { go: p.go, current: p.arg })),
      h("div", { className: "sm-pages-main" }, p.arg ? h(EntityPage, { id: p.arg, go: p.go, wide: true })
        : h(Empty, null, "Pick a page. Each one gathers what memory believes now, what changed, and every line that names it.")));
  }

  // ------------------------------------------------------------------ recall
  function GateBar(p) {
    var g = p.gate || {};
    if (g.kind !== "choice") {
      return h("div", { className: "sm-gate-other" }, g.kind === "skip" ? "Strong match (" + (g.value || 0).toFixed(2) + "): the gate was skipped."
        : g.kind === "none" ? "No memory came close enough to ask the gate." : g.kind === "degraded" ? "The decider was unavailable." : g.kind + (g.value != null ? " " + g.value : ""));
    }
    var parts = [["general", "General request", "var(--sm-quiet)"], ["none_fit", "None fits", "var(--sm-grey)"], ["memory", "A memory bears on it", "var(--sm-cyan)"]];
    return h("div", { className: "sm-gate" },
      h("div", { className: "sm-gate-bar" },
        parts.map(function (x) { return h("span", { key: x[0], style: { width: pct(g[x[0]]), background: x[2] } }); }),
        h("span", { className: "sm-gate-cut", style: { left: pct(p.cutoff) }, title: "Closes when “general” reaches " + p.cutoff })),
      h("ul", { className: "sm-legend" }, parts.map(function (x) {
        return h("li", { key: x[0] }, h("span", { className: "sm-swatch", style: { background: x[2] } }), h("span", { className: "sm-legend-label" }, x[1]),
          h("span", { className: "sm-legend-n" }, pct(g[x[0]])));
      })));
  }

  function RecallDetail(p) {
    var r = useApi("/recall/" + encodeURIComponent(p.id), 0);
    var ctx = useContext(Ctx);
    useEffect(function () { r.reload(); }, [ctx.version]);   // eslint-disable-line
    var d = r.data;
    if (r.error && !d) return h(Failed, { error: r.error, retry: r.reload });
    if (!d) return h(Loading);
    var g = d.gate || {};
    var why;
    if (d.verdict === "injected" || d.verdict === "possible") {
      why = g.kind === "choice" && (g.general || 0) >= d.cutoff
        ? "The best match scored " + (d.top_sim || 0).toFixed(2) + ", above the strong-match rule (" + d.strong_match + "), so memory went in even though the gate read a general request."
        : "“General” read " + pct(g.general) + ", under the " + d.cutoff + " cutoff, so " + d.items.length + " lines went into the prompt" + (d.verdict === "possible" ? ", marked as possible matches only because “none fits” outweighed every memory." : ".");
    } else if (d.verdict === "general") why = "Read as a general request (" + pct(g.general) + " ≥ " + d.cutoff + "): nothing was added.";
    else if (d.verdict === "nothing_found") why = "Nothing in memory was close enough to consider.";
    else if (d.verdict === "degraded") why = "The decider failed; only a very strong match could have passed.";
    else why = "The gate stayed closed.";
    var insights = [];
    var windows = d.items.filter(function (i) { return i.window; });
    var replies = windows.filter(function (i) { return (i.window.flags || []).indexOf("assistant") >= 0; }).length;
    var web = windows.filter(function (i) { return (i.window.flags || []).indexOf("external") >= 0; }).length;
    if (d.items.length >= 12 && (d.query || "").indexOf("?") < 0) insights.push("A statement pulled in " + d.items.length + " lines. Statements rarely need this much; worth watching.");
    if (web) insights.push(web + " line" + (web > 1 ? "s" : "") + " came from web pages. Check they belong.");
    if (windows.length > 3 && replies > windows.length / 2) insights.push("Most injected lines are the agent's own replies, which are weaker evidence than what people said.");
    var inj = {};
    d.items.forEach(function (i) { inj[i.id] = true; });
    var weights = {};
    ((d.reading && d.reading.options) || []).forEach(function (o) { var m = /^m(\d+)$/.exec(o.option); if (m) weights[+m[1] - 1] = o.p; });
    return h("article", { className: "sm-recall-d" },
      !p.wide && h("button", { type: "button", className: "sm-back", onClick: function () { p.go("recall"); } }, h(Icon, { name: "back" }), "All recalls"),
      h("div", { className: "sm-muted sm-mono" }, stamp(d.said) + (d.ms != null ? " · " + d.ms + " ms" : "") + (d.referential ? " · read with the previous message" : "") + " · " + trunc(d.session_id, 26)),
      h("h2", { className: "sm-recall-q" }, "“" + d.query + "”"),
      h(Card, { title: "The gate's reading" }, h(GateBar, { gate: g, cutoff: d.cutoff }), h("p", { className: "sm-lede" }, why)),
      insights.map(function (t, i) { return h("p", { key: i, className: "sm-insight" }, t); }),
      h(Card, { title: "Injected", count: d.items.length, plainCount: true },
        d.items.length ? h("ul", { className: "sm-lines" }, d.items.map(function (it) {
          var w = it.window;
          return h("li", { key: it.kind + it.id, className: "sm-line-item" },
            h("div", { className: "sm-mention-meta" },
              w ? h("span", { className: cx("sm-who", (w.flags || []).indexOf("assistant") >= 0 && "sm-who-reply") }, speakerLabel(w)) : h(Badge, { group: statusGroup(it) }),
              w && h("span", { className: "sm-mono sm-muted" }, stamp(w.said)),
              h("span", { className: "sm-mono sm-muted" }, "match " + (it.sim || 0).toFixed(2)),
              w && h(FlagTags, { flags: w.flags }),
              w && h(Btn, { small: true, className: "sm-keepout", onClick: function () { ctx.correct({ window: w, only: "drop" }); } }, "Keep out")),
            h("div", { className: "sm-mention-text" }, w ? w.text + (w.cut ? "…" : "") : sentence(it.fact)));
        })) : h(Empty, null, "Nothing went into the prompt.")),
      d.candidates.length ? h(Card, { title: "What the gate weighed" },
        h("ol", { className: "sm-weighed" }, d.candidates.map(function (c, i) {
          return h("li", { key: c.id || i },
            h("span", { className: "sm-weigh-bar" }, h("span", { style: { width: pct(weights[i] || 0) } })),
            h("span", { className: "sm-mono sm-weigh-p" }, weights[i] != null ? pct(weights[i]) : "–"),
            h("span", { className: "sm-weigh-text" }, h("span", { className: "sm-who" }, who(c.speaker)), " ", trunc(c.text, 160)),
            inj[c.id] ? h("span", { className: "sm-tag" }, "injected") : null);
        }))) : null);
  }

  function RecallList(p) {
    var list = useApi("/recall?limit=100", 15000);
    var items = (list.data && list.data.items) || [];
    return h("nav", { className: "sm-rlist", "aria-label": "Messages" },
      list.error && !list.data ? h(Failed, { error: list.error, retry: list.reload }) : !list.data ? h(Loading) :
      items.length ? h("ul", null, items.map(function (r) {
        var g = r.gate || {};
        return h("li", { key: r.id }, h("button", { type: "button", className: cx("sm-rrow", r.id === p.current && "sm-on"),
          "aria-current": r.id === p.current ? "true" : undefined, onClick: function () { p.go("recall", r.id); } },
          h("span", { className: "sm-rrow-q" }, trunc(r.query, 150)),
          h("span", { className: "sm-rrow-meta" }, h(VerdictChip, { verdict: r.verdict, n: r.n }),
            g.kind === "choice" ? h("span", { className: "sm-mono sm-muted" }, "g" + (g.general || 0).toFixed(2) + " m" + (g.memory || 0).toFixed(2)) : null,
            h("span", { className: "sm-muted" }, ago(r.said)))));
      })) : h(Empty, null, "No messages yet."));
  }

  function RecallView(p) {
    if (!p.wide) return p.arg ? h(RecallDetail, { id: p.arg, go: p.go, wide: false }) : h(RecallList, { go: p.go });
    return h("div", { className: "sm-pages" },
      h("aside", { className: "sm-pages-side" }, h(RecallList, { go: p.go, current: p.arg })),
      h("div", { className: "sm-pages-main" }, p.arg ? h(RecallDetail, { id: p.arg, go: p.go, wide: true })
        : h(Empty, null, "Pick a message to see how the gate read it and what went into the prompt.")));
  }

  // ------------------------------------------------------------------ corrections
  function CorrectSheet(p) {
    var t = p.target, ctx = useContext(Ctx);
    var opts = [];
    if (t.window && (!t.only || t.only === "relabel")) opts.push(["relabel", "Someone else said this", "Relabel who said the whole message; facts drawn from it are re-derived tonight."]);
    if (t.fact && !t.only) opts.push(["retract", "This fact is wrong: retract it", "It stops being recalled. The words it came from stay on record."]);
    if (t.window && (!t.only || t.only === "drop")) opts.push(["drop", "Keep this line out of recall", "For lines that are true but shouldn't come up."]);
    var optS = useState(opts.length === 1 ? opts[0][0] : null), opt = optS[0];
    var whyS = useState(""), toS = useState(""), busy = useState(false);
    var first = useRef(null);
    useEffect(function () {
      var f = function (e) { if (e.key === "Escape") p.close(); };
      window.addEventListener("keydown", f);
      if (first.current) first.current.focus();
      return function () { window.removeEventListener("keydown", f); };
    }, []);
    var ready = opt && whyS[0].trim() && (opt !== "relabel" || toS[0].trim());
    function apply() {
      if (!ready) return;
      busy[1](true);
      var body = { action: opt, reason: whyS[0].trim() };
      if (opt === "retract") body.fact_id = t.fact.id; else body.window_id = t.window.id;
      if (opt === "relabel") body.to = toS[0].trim();
      post("/correct", body).then(function (r) {
        p.close();
        var lines = r.changed + " line" + (r.changed === 1 ? "" : "s");
        ctx.notify(r.changed ? (opt === "relabel" ? "Relabelled " + lines : opt === "drop" ? "Kept " + lines + " out of recall" : "Fact retracted") : "Nothing needed changing", r.journal_id);
        ctx.changed();
      }, function (e) { busy[1](false); ctx.notify("Couldn't correct: " + errText(e)); });
    }
    return h("div", { className: "sm-modal-back", onClick: function (e) { if (e.target === e.currentTarget) p.close(); } },
      h("section", { className: "sm-modal", role: "dialog", "aria-modal": "true", "aria-label": "Correct" },
        h("span", { className: "sm-sheet-grip", "aria-hidden": "true" }),
        h("h2", { className: "sm-modal-title" }, t.fact ? sentence(t.fact.fact) : "Correct this line"),
        t.window && h(Quote, null, trunc(t.window.text, 260)),
        h("p", { className: "sm-hint" }, "Corrections change what was derived, never the words. You give a reason; it's journaled and can be undone."),
        h("div", { className: "sm-opts", role: "radiogroup" }, opts.map(function (o, i) {
          return h("button", { key: o[0], ref: i === 0 ? first : null, type: "button", role: "radio", "aria-checked": opt === o[0],
            className: cx("sm-opt", opt === o[0] && "sm-on"), onClick: function () { optS[1](o[0]); } },
            h("span", { className: "sm-opt-label" }, o[1]), h("span", { className: "sm-opt-hint" }, o[2]));
        })),
        opt === "relabel" && h("div", { className: "sm-field" }, h("label", { htmlFor: "sm-to" }, "Who said it?"),
          h("input", { id: "sm-to", value: toS[0], placeholder: "e.g. Claude", onChange: function (e) { toS[1](e.target.value); } })),
        opt && h("div", { className: "sm-field" }, h("label", { htmlFor: "sm-why" }, "Why?"),
          h("input", { id: "sm-why", value: whyS[0], placeholder: "e.g. my partner said this, not me",
            onChange: function (e) { whyS[1](e.target.value); }, onKeyDown: function (e) { if (e.key === "Enter") apply(); } })),
        h("div", { className: "sm-modal-actions" },
          h(Btn, { onClick: p.close }, "Cancel"),
          h(Btn, { primary: true, disabled: !ready || busy[0], onClick: apply }, "Apply"))));
  }

  // ------------------------------------------------------------------ the tab
  function Mindscape() {
    var rt = useRoute(), route = rt[0], go = rt[1];
    var wide = useMedia("(min-width: 900px)");
    var now = useApi("/now", 5000);
    var toastS = useState(null), toast = toastS[0], setToast = toastS[1];
    var verS = useState(0);
    var fixS = useState(null);
    useEffect(function () {
      if (!toast) return undefined;
      var t = setTimeout(function () { setToast(null); }, 7000);
      return function () { clearTimeout(t); };
    }, [toast]);
    var ctx = useMemo(function () {
      var c = {
        version: verS[0],
        changed: function () { verS[1](function (v) { return v + 1; }); },
        notify: function (msg, undoId) { setToast({ msg: msg, undoId: undoId, at: Date.now() }); },
        correct: function (target) { fixS[1](target); },
        undo: function (jid, after) {
          post("/undo", { journal_id: jid }).then(function () {
            setToast({ msg: "Undone", at: Date.now() });
            verS[1](function (v) { return v + 1; });
            if (after) after();
          }, function (e) { setToast({ msg: "Couldn't undo: " + errText(e), at: Date.now() }); });
        }
      };
      return c;
    }, [verS[0]]);

    var missing = now.error && /No Sophia store|404/.test(now.error) && !now.data;
    var body;
    if (missing) body = h(Card, { title: "No memory here yet" }, h("p", { className: "sm-lede" }, now.error),
      h("p", { className: "sm-hint" }, "Mindscape reads Sophia's store for the active profile. Set memory.provider to sophia and talk for a while."));
    else if (route.view === "graph") body = h(GraphView, { arg: route.arg, go: go, wide: wide, key: "graph" });
    else if (route.view === "pages") body = h(PagesView, { arg: route.arg, go: go, wide: wide });
    else if (route.view === "recall") body = h(RecallView, { arg: route.arg, go: go, wide: wide });
    else body = h(Overview, { now: now.data, go: go });

    var tab = function (v, cls) {
      var on = route.view === v[0];
      return h("a", { key: v[0], href: routeHref(v[0], ""), className: cx(cls, on && "sm-on"), "aria-current": on ? "page" : undefined,
        onClick: function (e) { e.preventDefault(); go(v[0]); } }, h(Icon, { name: v[2], size: cls === "sm-tabbar-item" ? 22 : 18 }), h("span", null, v[1]));
    };
    return h(Ctx.Provider, { value: ctx },
      h("div", { className: cx("sm", wide ? "sm-wide" : "sm-narrow") },
        h("header", { className: "sm-top" },
          wide && h("h1", { className: "sm-title" }, "Mindscape"),
          wide && h("nav", { className: "sm-tabs", "aria-label": "Mindscape views" }, VIEWS.map(function (v) { return tab(v, "sm-tab"); })),
          h(LivePill, { now: now.data, onClick: function () { go("overview"); } })),
        h("main", { className: "sm-body" }, body),
        !wide && h("nav", { className: "sm-tabbar", "aria-label": "Mindscape views" }, VIEWS.map(function (v) { return tab(v, "sm-tabbar-item"); })),
        fixS[0] && h(CorrectSheet, { target: fixS[0], close: function () { fixS[1](null); } }),
        toast && h("div", { className: "sm-toast", role: "status" }, h("span", null, toast.msg),
          toast.undoId ? h(Btn, { small: true, onClick: function () { var id = toast.undoId; setToast(null); ctx.undo(id); } }, "Undo") : null)));
  }

  window.__HERMES_PLUGINS__.register("sophia", Mindscape);
})();
