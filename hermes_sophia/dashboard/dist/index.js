/* Sophia — the Hermes dashboard tab for watching, curating and configuring Sophia's memory.
 * Plain IIFE against the dashboard's plugin SDK (its React, its authenticated fetch); no build step.
 * Views: Overview (live state, last night, what needs a look), Graph, Mindscape (the pages), Recall, Settings. Sub-views live in the URL
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
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function when(h) {       // "2026-09-06/2026-09-08" -> "Sep 6 – 8"; "2026-08-17T09:30" -> "Aug 17, 09:30"; "2026-09" -> "Sep 2026"
    if (!h) return "";
    var thisYear = new Date().getFullYear();
    function one(x) {
      var m = /^(\d{4})-(\d\d)(?:-(\d\d))?(?:T(\d\d:\d\d))?$/.exec(x);
      if (!m) return null;
      var mon = MONTHS[+m[2] - 1];
      if (!m[3]) return { text: mon + " " + m[1], y: m[1], mon: mon };
      return { text: mon + " " + (+m[3]) + (+m[1] !== thisYear ? ", " + m[1] : "") + (m[4] ? ", " + m[4] : ""), y: m[1], mon: mon, d: +m[3] };
    }
    var parts = String(h).split("/");
    var a = one(parts[0]), b = parts[1] ? one(parts[1]) : null;
    if (!a) return h;
    if (!parts[1]) return a.text;
    if (!b) return a.text + " – " + parts[1];
    return a.mon === b.mon && a.y === b.y && b.d ? a.text + " – " + b.d : a.text + " – " + b.text;
  }
  function nightDate(id) {
    var m = /^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)/.exec(id || "");
    if (!m) return id === "manual" ? "by hand" : (id || "");
    return day(new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]).getTime() / 1000) + " · " + m[4] + ":" + m[5];
  }

  // ------------------------------------------------------------------ icons
  var ICONS = {
    pulse: '<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/>',
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
    more: '<path d="M5 12h.01M12 12h.01M19 12h.01" stroke-width="3"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'
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

  var VIEWS = [["overview", "Overview", "grid"], ["graph", "Graph", "graph"], ["pages", "Mindscape", "book"], ["recall", "Recall", "message"],
               ["continuity", "Continuity", "pulse"], ["settings", "Settings", "gear"]];
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
    var fixed = { "Memory notes": "var(--sm-green)", "Web": "var(--sm-amber)", "Tool steps": "var(--sm-grey)", "Others": "var(--sm-orchid)" };
    fixed[p.user] = "var(--sm-violet)";
    fixed[p.agent] = "var(--sm-cyan)";
    var parts = z.speakers.map(function (s, i) { return { label: s[0], v: s[1], color: fixed[s[0]] || SPEAKER_COLORS[i % SPEAKER_COLORS.length] }; });
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
      detail = (it.happens ? "Planned for " + when(it.happens) + ". " : "") + "The date passed and nobody said whether it happened.";
      extra = src ? h("div", { className: "sm-q-src" }, h(Quote, null, trunc(src.text, 220)), h("div", { className: "sm-src" }, speakerLabel(src) + " · " + stamp(src.said))) : null;
      actions = [["It happened", true, function () { act(post("/plan", { fact_id: it.id, outcome: "happened" }), "Marked as happened"); }],
                 ["It didn’t", false, function () { act(post("/plan", { fact_id: it.id, outcome: "didnt" }), "Marked as didn’t happen"); }],
                 ["Leave", false, function () { review("Left unconfirmed"); }]];
    } else if (it.type === "prompt_injection") {
      kind = ["Kept out of memory", "var(--sm-cyan)"];
      title = "A web page tried to give the assistant instructions";
      detail = (it.url || "A page") + " was recognised" + (it.p != null ? " (" + it.p.toFixed(2) + ")" : "") +
        " and is kept out of recall from now on. Recalls from before the night may have used it; the Recall view shows where.";
      actions = [["Seen", false, function () { review("Noted"); }]];
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
      case "canonical_relation": return ["“" + (d.relation || "is") + "” became a known relation", d.instances + " uses"];
      case "task_succeeded": return ["Task card: " + d.goal, d.steps + (d.steps === 1 ? " step" : " steps")];
      case "recall_miss": return ["Recall missed: " + d.question, ""];
      case "prompt_injection": return ["A web page tried to instruct the assistant: " + d.url, "kept out of recall · " + d.p];
      case "dropped": return ["Web page kept out of recall: " + d.url, d.p >= 0.6 ? "mostly boilerplate" : ""];
      case "dropped_error_payload": return ["Web page was an error page: " + d.url, "kept out of recall"];
      case "failed": return ["Step " + e.step + " failed", trunc((d && d.error) || "", 120)];
      case "yielded": return ["The night yielded", String(e.detail)];
      default:
        if (/^task_/.test(e.kind)) return ["Task card (" + e.kind.slice(5).replace(/_/g, " ") + "): " + (d.goal || ""), d.steps ? d.steps + (d.steps === 1 ? " step" : " steps") : ""];
        return [e.kind.replace(/_/g, " "), typeof d === "string" ? d : ""];
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
      h("div", { className: "sm-grid3" }, h(LastNight, { night: d.night }), h(InMemory, { sizes: d.sizes, user: d.user, agent: d.agent }), h(RecallWeek, { recall: d.recall })),
      h("div", { className: "sm-grid3" }, h(Queue, { go: p.go }), h(Changes, null)));
  }

  // ------------------------------------------------------------------ graph
  var EDGE = {
    now: { color: "var(--sm-edge)", dash: "" },
    planned: { color: "var(--sm-amber)", dash: "2 5" },
    check: { color: "var(--sm-amber)", dash: "2 5" },
    before: { color: "var(--sm-grey)", dash: "7 6" }
  };
  var CLUSTER_COLORS = ["#7fdbff", "#b39dff", "#f2be72", "#8fe3b0", "#f2a7d8", "#9fb4ff", "#ffa38a", "#6ee7d7",
                        "#e6d36f", "#c9a6ff", "#86c8ff", "#f59ec0"];
  function clusterColor(c) { return c == null || c < 0 ? "var(--sm-grey)" : CLUSTER_COLORS[c % CLUSTER_COLORS.length]; }
  function radius(n) { return n.subject ? Math.min(30, 7 + 2.6 * Math.sqrt(n.facts)) : Math.min(12, 4 + Math.sqrt(n.facts)); }

  // A small force layout. Placed nodes keep their place (they move a little); new ones start beside a placed
  // neighbour, or beside their cluster's anchor. ``group`` (node -> cluster) also pulls each cluster together.
  function settle(vis, links, pos, iters, group) {
    var n = vis.length, P = new Array(n), idx = {};
    vis.forEach(function (v, i) { idx[v.id] = i; });
    var fresh = 0, groups = {};
    if (group) vis.forEach(function (v) { var c = group[v.id]; if (c != null && c >= 0) groups[c] = true; });
    var gl = Object.keys(groups).map(Number).sort(function (a, b) { return a - b; }), G = gl.length || 1;
    var anchor = {};
    gl.forEach(function (c, i) {
      if (i === 0) { anchor[c] = { x: 0, y: 0 }; return; }
      var a = 2 * Math.PI * (i - 1) / Math.max(1, G - 1) - Math.PI / 2, r = 300 + 55 * Math.sqrt(G);
      anchor[c] = { x: Math.cos(a) * r, y: Math.sin(a) * r };
    });
    vis.forEach(function (v, i) {
      var p = pos[v.id];
      if (!p) {
        var near = null;
        for (var k = 0; k < links.length && !near; k++) {
          var l = links[k];
          if (l.a === v.id && pos[l.b]) near = pos[l.b];
          else if (l.b === v.id && pos[l.a]) near = pos[l.a];
        }
        var ang = Math.random() * Math.PI * 2, base = { x: 0, y: 0 }, dist = 40 + Math.random() * 120;
        if (near) { base = near; dist = 30 + Math.random() * 30; }
        else if (group && anchor[group[v.id]]) { base = anchor[group[v.id]]; dist = 20 + Math.random() * 60; }
        p = pos[v.id] = { x: base.x + Math.cos(ang) * dist, y: base.y + Math.sin(ang) * dist, fresh: true };
        fresh++;
      }
      P[i] = p;
    });
    if (!fresh && iters < 100) return;
    var R = vis.map(radius), L = links.map(function (l) { return [idx[l.a], idx[l.b], l.len, l.k]; })
      .filter(function (l) { return l[0] != null && l[1] != null; });
    var gi = group ? vis.map(function (v) { var c = group[v.id]; return c == null || c < 0 ? -1 : c; }) : null;
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
      if (gi) {                                              // each cluster gathers at its own anchor
        for (var h2 = 0; h2 < n; h2++) {
          var an = anchor[gi[h2]];
          if (!an) continue;
          dx[h2] -= (P[h2].x - an.x) * 0.05; dy[h2] -= (P[h2].y - an.y) * 0.05;
        }
      }
      for (var q = 0; q < n; q++) {
        if (!gi || gi[q] < 0) { dx[q] -= P[q].x * 0.012; dy[q] -= P[q].y * 0.012; }
        var lim = P[q].fresh ? temp : temp * 0.3, mag = Math.sqrt(dx[q] * dx[q] + dy[q] * dy[q]);
        if (mag > lim) { dx[q] *= lim / mag; dy[q] *= lim / mag; }
        P[q].x += dx[q]; P[q].y += dy[q];
      }
    }
    P.forEach(function (p) { p.fresh = false; });
  }

  function hull(pts) {                                       // convex hull (monotone chain)
    if (pts.length < 3) return pts.slice();
    var p = pts.slice().sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var cross = function (o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); };
    var lo = [], up = [];
    p.forEach(function (q) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); });
    for (var i = p.length - 1; i >= 0; i--) { var q = p[i]; while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
    up.pop(); lo.pop();
    return lo.concat(up);
  }

  // everything within ``hops`` of ``center``; the last ring is trimmed to the best-connected when it would pass ``cap``
  function neighborhood(center, hops, adj, degree, cap) {
    var depth = {}, order = [center], frontier = [center], trimmed = 0;
    depth[center] = 0;
    for (var d = 1; d <= hops && frontier.length; d++) {
      var next = [];
      frontier.forEach(function (n) {
        (adj[n] || []).forEach(function (m) { if (depth[m] == null) { depth[m] = d; next.push(m); } });
      });
      if (order.length + next.length > cap) {
        next.sort(function (a, b) { return (degree[b] || 0) - (degree[a] || 0); });
        var keep = next.slice(0, Math.max(0, cap - order.length));
        next.slice(keep.length).forEach(function (m) { delete depth[m]; });
        trimmed += next.length - keep.length;
        next = keep;
      }
      order = order.concat(next);
      frontier = next;
    }
    return { depth: depth, ids: order, trimmed: trimmed };
  }

  function Seg(p) {                                           // a small segmented control
    return h("div", { className: "sm-seg", role: "group", "aria-label": p.label },
      p.caption ? h("span", { className: "sm-seg-caption", "aria-hidden": "true" }, p.caption) : null,
      p.options.map(function (o) {
        var on = p.value === o[0];
        return h("button", { key: String(o[0]), type: "button", className: on ? "sm-on" : "", "aria-pressed": on,
          "aria-label": o[2] || undefined, onClick: function () { p.onChange(o[0]); } }, o[1]);
      }));
  }

  function GraphView(p) {
    var g = useApi("/graph", 0);
    var ctx = useContext(Ctx);
    useEffect(function () { g.reload(); }, [ctx.version]);   // eslint-disable-line
    var wide = p.wide, data = g.data;
    var st = useState({ view: null, hops: null, center: p.arg || null, colorBy: "cluster" }), vs = st[0], setVs = st[1];
    var selS = useState(p.arg || null), sel = selS[0], setSel = selS[1];
    var showS = useState({ now: true, planned: true, check: true, before: true }), show = showS[0], setShow = showS[1];
    var togS = useState(true), together = togS[0];
    var hullS = useState(true), hulls = hullS[0];
    var focusS = useState(null), focusCl = focusS[0], setFocus = focusS[1];
    var qS = useState(""), query = qS[0];
    var sheetS = useState(false), sheetOpen = sheetS[0];
    var keyS = useState(function () { try { return localStorage.getItem("sophia.graph.key") !== "hidden"; } catch (e) { return true; } });
    var showKey = keyS[0];
    var posN = useRef({}), posE = useRef({});
    var viewS = useState({ k: 1, x: 0, y: 0 }), view = viewS[0], setView = viewS[1];
    var boxRef = useRef(null), svgRef = useRef(null);
    var sizeS = useState({ w: 0, h: 0 }), size = sizeS[0];
    var refit = useRef(true), picked = useRef(0), lastTap = useRef({ id: null, t: 0 });

    // the dashboard's own defaults (Settings), once the data arrives
    var mode = vs.view || (data && data.settings && data.settings.view) || "neighborhood";
    var hops = vs.hops || (data && data.settings && data.settings.hops) || 2;

    useEffect(function () {
      if (p.arg) { setSel(p.arg); setVs(function (v) { return Object.assign({}, v, { center: p.arg, view: "neighborhood" }); }); refit.current = true; }
    }, [p.arg]);
    useEffect(function () {
      var el = boxRef.current;
      if (!el) return undefined;
      var last = { w: 0, h: 0 };
      var ro = new ResizeObserver(function () {
        var w = el.clientWidth, hh = el.clientHeight;
        if (last.w && (w !== last.w || hh !== last.h)) {
          var dw = (w - last.w) / 2, dh = (hh - last.h) / 2;
          setView(function (v) { return { k: v.k, x: v.x + dw, y: v.y + dh }; });
        }
        last = { w: w, h: hh };
        sizeS[1]({ w: w, h: hh });
      });
      ro.observe(el);
      return function () { ro.disconnect(); };
    }, [!!data]);

    var byId = useMemo(function () {
      var m = {};
      (data ? data.nodes : []).forEach(function (n) { m[n.id] = n; });
      return m;
    }, [data]);
    var clusters = (data && data.clusters) || [];
    var defaultCenter = useMemo(function () {
      if (!data) return null;
      var you = data.nodes.filter(function (n) { return n.role === "user"; })[0];
      return (you || data.nodes.slice().sort(function (a, b) { return b.facts - a.facts; })[0] || {}).id || null;
    }, [data]);
    var center = vs.center && byId[vs.center] ? vs.center : defaultCenter;

    var shown = useMemo(function () {
      if (!data || !center) return { nodes: [], edges: [], links: [], ties: [], depth: {}, trimmed: 0 };
      var edges = data.edges.filter(function (e) { return show[statusGroup(e)]; });
      var ties = together ? data.together : [];
      var adj = {}, degree = {};
      var link = function (a, b) { (adj[a] = adj[a] || []).push(b); (adj[b] = adj[b] || []).push(a); degree[a] = (degree[a] || 0) + 1; degree[b] = (degree[b] || 0) + 1; };
      edges.forEach(function (e) { link(e.s, e.o); });
      ties.forEach(function (t) { link(t.a, t.b); });
      var ids = {}, depth = {}, trimmed = 0;
      if (mode === "neighborhood") {
        var nb = neighborhood(center, hops, adj, degree, wide ? 360 : 220);
        nb.ids.forEach(function (x) { ids[x] = true; });
        depth = nb.depth; trimmed = nb.trimmed;
      } else {
        data.nodes.slice().sort(function (a, b) { return b.facts - a.facts; }).slice(0, 700)
          .forEach(function (n) { ids[n.id] = true; });
      }
      var vEdges = edges.filter(function (e) { return ids[e.s] && ids[e.o]; });
      var vTies = ties.filter(function (t) { return ids[t.a] && ids[t.b]; });
      var nodes = data.nodes.filter(function (n) { return ids[n.id]; });
      // a busy node's facts sit farther out, over three staggered rings, so their labels don't collide
      var seen = {}, links = [], deg = {}, nth = {};
      vEdges.forEach(function (e) { deg[e.s] = (deg[e.s] || 0) + 1; deg[e.o] = (deg[e.o] || 0) + 1; });
      vEdges.forEach(function (e) {
        var key = e.s < e.o ? e.s + "|" + e.o : e.o + "|" + e.s;
        if (seen[key]) return;
        seen[key] = true;
        var hub = byId[e.s].subject && byId[e.o].subject;
        var owner = (deg[e.s] || 0) >= (deg[e.o] || 0) ? e.s : e.o, dg = deg[owner] || 0;
        var spread = Math.min(200, 2.2 * dg);
        nth[owner] = (nth[owner] || 0) + 1;
        var ring = dg > 20 ? (nth[owner] % 3) * 46 : 0;
        var across = mode === "everything" && byId[e.s].cluster !== byId[e.o].cluster;
        links.push({ a: e.s, b: e.o, len: (hub ? 110 + spread * 1.4 : 30 + radius(byId[e.s]) + radius(byId[e.o]) + spread + ring) + (across ? 160 : 0),
                     k: (hub ? 0.02 : 0.08) * (across ? 0.1 : 1) });
      });
      vTies.forEach(function (t) {
        var across = mode === "everything" && byId[t.a].cluster !== byId[t.b].cluster;
        links.push({ a: t.a, b: t.b, len: 220, k: 0.004 * Math.min(t.n, 5) * (across ? 0.1 : 1) });
      });
      return { nodes: nodes, edges: vEdges, links: links, ties: vTies, depth: depth, trimmed: trimmed };
    }, [data, byId, center, mode, hops, show, together, wide]);

    var pos = mode === "everything" ? posE : posN;
    var groupOf = useMemo(function () {
      var m = {};
      (data ? data.nodes : []).forEach(function (n) { m[n.id] = n.cluster; });
      return m;
    }, [data]);
    var laid = useMemo(function () {
      if (!shown.nodes.length) return 0;
      settle(shown.nodes, shown.links, pos.current, shown.nodes.length > 250 ? 150 : 220, mode === "everything" ? groupOf : null);
      return Date.now();
    }, [shown, mode]);

    var fitTo = useCallback(function (ids, maxK) {
      if (!ids.length || !size.w) return;
      var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      ids.forEach(function (id) {
        var q = pos.current[id];
        if (!q) return;
        x0 = Math.min(x0, q.x); y0 = Math.min(y0, q.y); x1 = Math.max(x1, q.x); y1 = Math.max(y1, q.y);
      });
      if (x0 === Infinity) return;
      var hh = wide ? size.h : Math.max(180, size.h - (sel ? 170 : 0));
      var m = 50, k = Math.min((size.w - 2 * m) / Math.max(1, x1 - x0), (hh - 2 * m) / Math.max(1, y1 - y0));
      k = Math.max(wide ? 0.12 : 0.3, Math.min(maxK || 2.2, k));
      setView({ k: k, x: size.w / 2 - k * (x0 + x1) / 2, y: hh / 2 - k * (y0 + y1) / 2 });
    }, [size, wide, mode, sel]);
    var fit = useCallback(function () { fitTo(shown.nodes.map(function (n) { return n.id; }), 1.8); }, [shown, fitTo]);
    var topLabels = useMemo(function () {                     // which names show at a glance
      var m = {};
      shown.nodes.slice().sort(function (a, b) { return b.facts - a.facts; }).slice(0, mode === "everything" ? 28 : 60)
        .forEach(function (n) { m[n.id] = true; });
      return m;
    }, [shown, mode]);

    useEffect(function () {                                   // after a change of view, centre, hops or cluster
      if (!laid || !size.w || !refit.current) return;
      refit.current = false;
      if (focusCl != null && mode === "everything") {
        fitTo(shown.nodes.filter(function (n) { return n.cluster === focusCl; }).map(function (n) { return n.id; }), 1.8);
      } else fit();
    }, [laid, size, focusCl]);   // eslint-disable-line

    useEffect(function () {                                   // the panel opening mustn't hide what was just picked
      var q = sel && pos.current[sel];
      if (!q || !size.w) return;
      var sx = view.x + q.x * view.k, sy = view.y + q.y * view.k;
      if (sx < 40 || sx > size.w - 40 || sy < 40 || sy > size.h - 40) {
        setView(function (v) { return { k: v.k, x: size.w / 2 - v.k * q.x, y: size.h / 2 - v.k * q.y }; });
      }
    }, [size.w, sel]);   // eslint-disable-line

    function change(next) { refit.current = true; setVs(function (v) { return Object.assign({}, v, next); }); }
    function explore(id) { setSel(id); setFocus(null); change({ center: id, view: "neighborhood" }); }
    function focusCluster(id) {
      refit.current = true;
      setFocus(function (f) { return f === id ? null : id; });
      if (mode !== "everything") setVs(function (v) { return Object.assign({}, v, { view: "everything" }); });
    }

    // pan (drag), zoom (wheel, pinch), tap to select, double-tap to explore from there
    var ptrs = useRef({}), gesture = useRef(null);
    function toLocal(e) {
      var r = svgRef.current.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }
    function zoomAt(pt, factor) {
      setView(function (v) {
        var k = Math.max(0.08, Math.min(4, v.k * factor)), f = k / v.k;
        return { k: k, x: pt.x - (pt.x - v.x) * f, y: pt.y - (pt.y - v.y) * f };
      });
    }
    useEffect(function () {
      var el = svgRef.current;
      if (!el) return undefined;
      var onWheel = function (e) { e.preventDefault(); zoomAt(toLocal(e), Math.exp(-e.deltaY * 0.0015)); };
      el.addEventListener("wheel", onWheel, { passive: false });
      return function () { el.removeEventListener("wheel", onWheel); };
    }, [!!data]);
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
        var k = Math.max(0.08, Math.min(4, gs.view.k * d / gs.d)), f = k / gs.view.k;
        setView({ k: k, x: gs.mid.x - (gs.mid.x - gs.view.x) * f, y: gs.mid.y - (gs.mid.y - gs.view.y) * f });
      }
    }
    function onUp(e) {
      var gs = gesture.current;
      delete ptrs.current[e.pointerId];
      if (gs && gs.type === "pan" && !gs.moved) {
        if (gs.node) {
          var now = Date.now(), twice = lastTap.current.id === gs.node && now - lastTap.current.t < 400;
          lastTap.current = { id: gs.node, t: now };
          picked.current = now;
          if (twice) explore(gs.node);
          else { if (sel !== gs.node) sheetS[1](false); setSel(gs.node); }
        } else setSel(null);
      }
      if (!Object.keys(ptrs.current).length) gesture.current = null;
    }
    function find(e) {
      e.preventDefault();
      var q = query.trim().toLowerCase();
      if (!q || !data) return;
      var hit = data.nodes.filter(function (n) { return n.label.toLowerCase().indexOf(q) >= 0; })
        .sort(function (a, b) { return (b.subject - a.subject) || (b.facts - a.facts); })[0];
      if (!hit) { ctx.notify("Nothing in the graph matches “" + query + "”."); return; }
      explore(hit.id);
    }

    if (g.error && !data) return h(Failed, { error: g.error, retry: g.reload });
    if (!data) return h(Loading);

    var near = {};
    if (sel) {
      near[sel] = true;
      shown.edges.forEach(function (e) { if (e.s === sel) near[e.o] = true; if (e.o === sel) near[e.s] = true; });
    }
    var selEdges = sel ? shown.edges.filter(function (e) { return e.s === sel || e.o === sel; }) : [];
    var everything = mode === "everything";
    var colorOf = function (n) { return vs.colorBy === "cluster" ? clusterColor(n.cluster) : ROLE[n.role][1]; };
    var dimmed = function (n) {
      if (focusCl != null && everything) return n.cluster !== focusCl;
      return sel && !near[n.id];
    };

    // clusters: a soft outline around each, and its name
    var hullEls = [];
    if (everything && hulls) {
      clusters.forEach(function (c) {
        var pts = shown.nodes.filter(function (n) { return n.cluster === c.id; })
          .map(function (n) { var q = pos.current[n.id]; return q ? [q.x, q.y] : null; }).filter(Boolean);
        if (pts.length < 3) return;
        var hp = hull(pts), col = clusterColor(c.id), faded = focusCl != null && focusCl !== c.id;
        hullEls.push(h("path", { key: "h" + c.id, d: "M" + hp.map(function (q) { return q[0] + "," + q[1]; }).join("L") + "Z",
          fill: col, fillOpacity: faded ? 0.02 : 0.07, stroke: col, strokeOpacity: faded ? 0.04 : 0.14,
          strokeWidth: 30 / view.k, strokeLinejoin: "round", className: "sm-hull" }));
        var top = hp.reduce(function (a, q) { return q[1] < a[1] ? q : a; }, hp[0]);
        var cxm = pts.reduce(function (a, q) { return a + q[0]; }, 0) / pts.length;
        if (c.size >= 4) hullEls.push(h("text", { key: "t" + c.id, x: cxm, y: top[1] - 30 / view.k, textAnchor: "middle",
          className: "sm-cluster-label", fill: col, fontSize: 13 / view.k, opacity: faded ? 0.3 : 1 }, trunc(c.label, 42)));
      });
    }

    var svg = h("svg", { ref: svgRef, className: "sm-svg", width: size.w, height: size.h, role: "img",
        "aria-label": "Memory graph: " + shown.nodes.length + " people and things, " + shown.edges.length + " facts shown",
        onPointerDown: onDown, onPointerMove: onMove, onPointerUp: onUp, onPointerCancel: onUp },
      h("g", { transform: "translate(" + view.x + "," + view.y + ") scale(" + view.k + ")" },
        hullEls,
        shown.ties.map(function (t) {
          var a = pos.current[t.a], b = pos.current[t.b];
          if (!a || !b) return null;
          return h("line", { key: "t" + t.a + "|" + t.b, x1: a.x, y1: a.y, x2: b.x, y2: b.y, className: "sm-tie", strokeWidth: Math.min(4, 0.6 + t.n * 0.4) / view.k });
        }),
        shown.edges.map(function (e) {
          var a = pos.current[e.s], b = pos.current[e.o];
          if (!a || !b) return null;
          var es = EDGE[statusGroup(e)], lit = sel && (e.s === sel || e.o === sel);
          var faded = (focusCl != null && everything && (byId[e.s].cluster !== focusCl || byId[e.o].cluster !== focusCl)) || (sel && !lit);
          return h("line", { key: e.id, x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: es.color, strokeDasharray: es.dash,
            strokeWidth: (lit ? 2.2 : 1.2) / Math.sqrt(view.k), opacity: faded ? 0.12 : lit ? 1 : 0.5 });
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
          var r = radius(n), on = n.id === sel, isCenter = !everything && n.id === center, col = colorOf(n), dim = dimmed(n);
          var d = shown.depth[n.id];
          var showLabel = on || isCenter || (sel && near[n.id]) || view.k >= (everything ? 1.6 : 1.25) ||
            (topLabels[n.id] && !dim) || (!everything && d != null && d <= 1) ||
            (focusCl != null && everything && n.cluster === focusCl && n.subject);
          return h("g", { key: n.id, "data-node": n.id, className: cx("sm-node", dim && "sm-dim"), transform: "translate(" + q.x + "," + q.y + ")" },
            h("circle", { r: Math.max(r, (wide ? 10 : 22) / view.k), fill: "transparent" }),
            (on || isCenter) && h("circle", { r: r + 6, className: isCenter && !on ? "sm-halo sm-halo-center" : "sm-halo" }),
            h("circle", { r: Math.max(r, 3.5 / view.k), fill: col, fillOpacity: n.subject ? 0.24 : 0.16, stroke: col, strokeWidth: (on ? 2.5 : 1.5) / view.k }),
            showLabel && h("text", { y: r + 13 / view.k, className: cx("sm-node-label", n.subject && "sm-node-hub"), fontSize: (n.subject ? 12.5 : 11) / view.k,
              textAnchor: "middle" }, trunc(n.label, n.subject ? 26 : 30)));
        })));

    var selNode = sel ? byId[sel] : null;
    var cl = selNode && selNode.cluster >= 0 ? clusters.filter(function (c) { return c.id === selNode.cluster; })[0] : null;
    var detail = selNode ? h(GraphDetail, { node: selNode, edges: data.edges.filter(function (e) { return e.s === sel || e.o === sel; }),
      byId: byId, cluster: cl, isCenter: !everything && sel === center, hops: hops, go: p.go,
      pick: function (id) { picked.current = Date.now(); setSel(id); },
      explore: function () { explore(sel); }, focusCluster: function () { if (cl) focusCluster(cl.id); },
      close: function () { setSel(null); } }) : null;

    var toolbar = h("div", { className: "sm-graph-tools" },
      h(IconBtn, { icon: "plus", label: "Zoom in", onClick: function () { zoomAt({ x: size.w / 2, y: size.h / 2 }, 1.3); } }),
      h(IconBtn, { icon: "minus", label: "Zoom out", onClick: function () { zoomAt({ x: size.w / 2, y: size.h / 2 }, 1 / 1.3); } }),
      h(IconBtn, { icon: "fit", label: "Fit to screen", onClick: fit }));

    var counts = {};
    data.edges.forEach(function (e) { var k = statusGroup(e); counts[k] = (counts[k] || 0) + 1; });
    var filterEls = [["now", "Current"], ["planned", "Planned"], ["check", "Date passed"], ["before", "Changed or cancelled"]].map(function (f) {
      var on = show[f[0]];
      return h("button", { key: f[0], type: "button", className: cx("sm-toggle", on && "sm-on"), "aria-pressed": on,
        onClick: function () { setShow(function (s) { var n = Object.assign({}, s); n[f[0]] = !s[f[0]]; return n; }); } },
        h("span", { className: "sm-line sm-line-" + f[0] }), h("span", null, f[1]), h("span", { className: "sm-toggle-n" }, counts[f[0]] || 0));
    });
    var search = h("form", { className: "sm-search", onSubmit: find, role: "search" },
      h(Icon, { name: "search", size: 18 }),
      h("input", { type: "search", value: query, placeholder: "Find a person, place, thing…", "aria-label": "Find in the graph",
        onChange: function (e) { qS[1](e.target.value); } }));
    var centerNode = byId[center];
    var viewControls = h("div", { className: "sm-graph-view" },
      h(Seg, { label: "View", value: mode, onChange: function (v) { setFocus(null); change({ view: v }); },
        options: [["neighborhood", "Neighborhood"], ["everything", "Everything"]] }),
      !everything && h(Seg, { label: "Hops", caption: "Hops", value: hops, onChange: function (v) { change({ hops: v }); },
        options: [[1, "1", "1 hop"], [2, "2", "2 hops"], [3, "3", "3 hops"], [4, "4", "4 hops"]] }),
      h(Seg, { label: "Colour by", value: vs.colorBy, onChange: function (v) { setVs(function (x) { return Object.assign({}, x, { colorBy: v }); }); },
        options: [["cluster", "Clusters"], ["role", "Who"]] }));
    var stat = h("p", { className: "sm-graph-stat" }, everything
      ? "All " + shown.nodes.length + " people and things, in " + clusters.length + " clusters" + (focusCl != null ? " · one in focus" : "")
      : [hops + (hops === 1 ? " hop" : " hops") + " around ", h("strong", { key: "c" }, centerNode ? centerNode.label : "?"),
         ": " + (shown.nodes.length - 1) + " people and things" + (shown.trimmed ? " (the " + shown.trimmed + " least connected left out)" : "")]);
    var legend = clusters.length ? h("div", { className: "sm-clusters" },
      h("div", { className: "sm-sub-head" }, "Clusters"),
      h("ul", null, clusters.map(function (c) {
        var on = focusCl === c.id;
        return h("li", { key: c.id }, h("button", { type: "button", className: cx("sm-cluster", on && "sm-on"), "aria-pressed": on,
          onClick: function () { focusCluster(c.id); } },
          h("span", { className: "sm-swatch", style: { background: clusterColor(c.id) } }),
          h("span", { className: "sm-cluster-name" }, c.label), h("span", { className: "sm-index-n" }, c.size)));
      }))) : null;
    var extras = h("div", { className: "sm-graph-extras" },
      h("label", { className: "sm-check" }, h("input", { type: "checkbox", checked: together, onChange: function (e) { togS[1](e.target.checked); refit.current = true; } }), "Mentioned together (faint lines)"),
      everything && h("label", { className: "sm-check" }, h("input", { type: "checkbox", checked: hulls, onChange: function (e) { hullS[1](e.target.checked); } }), "Outline clusters"));

    var hideKey = function () { keyS[1](false); try { localStorage.setItem("sophia.graph.key", "hidden"); } catch (e) { /* private window */ } };
    var key = showKey ? h("section", { className: "sm-graph-key", "aria-label": "What this is" },
      h("div", { className: "sm-graph-key-head" },
        h("strong", null, everything ? "Everything memory knows about" : "Who and what memory knows about"),
        h(IconBtn, { icon: "close", label: "Hide this explanation", onClick: hideKey, size: 16 })),
      h("ul", null,
        h("li", null, h("span", { className: "sm-key-dot" }), h("span", null, "A circle is a person, place or thing; bigger means more facts.")),
        h("li", null, h("span", { className: "sm-line sm-line-now" }), h("span", null, "A line is a fact: solid is current, ",
          h("span", { className: "sm-key-word sm-amber" }, "dotted"), " is planned or past its date, ",
          h("span", { className: "sm-key-word" }, "dashed"), " has changed.")),
        everything ? h("li", null, h("span", { className: "sm-key-hull" }), h("span", null, "An outline is a cluster: what gets talked about together."))
          : h("li", null, h("span", { className: "sm-key-ring" }), h("span", null, "The dashed ring is the centre; everything shown is within " + hops + (hops === 1 ? " hop" : " hops") + " of it.")),
        h("li", { className: "sm-muted" }, h("span", null, "Click a circle to see its facts. Double-click it to explore from there.")))) : null;
    if (wide) {
      return h("div", { className: cx("sm-graph sm-graph-wide", selNode && "sm-graph-has-detail") },
        h("aside", { className: "sm-graph-side", "aria-label": "Graph controls" },
          search, viewControls, stat,
          h("div", { className: "sm-sub-head" }, "Show"), h("div", { className: "sm-toggles" }, filterEls),
          extras, legend,
          !showKey && h("button", { type: "button", className: "sm-link sm-key-again", onClick: function () { keyS[1](true); try { localStorage.removeItem("sophia.graph.key"); } catch (e) { /* ignore */ } } }, "What am I looking at?")),
        h("div", { className: "sm-graph-canvas", ref: boxRef }, svg, key, toolbar),
        selNode && h("aside", { className: "sm-graph-detail", "aria-label": "Selected" }, detail));
    }
    return h("div", { className: "sm-graph sm-graph-narrow" },
      search, viewControls, stat,
      h("div", { className: "sm-chips-row" }, filterEls),
      h("div", { className: "sm-graph-canvas", ref: boxRef }, svg, toolbar),
      extras, legend,
      detail && h("section", { className: cx("sm-sheet", !sheetOpen && "sm-sheet-folded"), "aria-label": "Selected",
        // the click a phone sends after a tap lands on whatever just appeared under the finger: ignore it
        onClickCapture: function (e) { if (Date.now() - picked.current < 450) { e.stopPropagation(); e.preventDefault(); } } },
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
      p.cluster && h("button", { type: "button", className: "sm-cluster sm-cluster-inline", onClick: p.focusCluster, title: "Show this cluster" },
        h("span", { className: "sm-swatch", style: { background: clusterColor(p.cluster.id) } }),
        h("span", { className: "sm-cluster-name" }, "Cluster: " + p.cluster.label), h("span", { className: "sm-index-n" }, p.cluster.size)),
      h("div", { className: "sm-gd-actions" },
        n.entity && h(Btn, { primary: true, onClick: function () { p.go("pages", n.id); } }, "Open page"),
        !p.isCenter && h(Btn, { onClick: p.explore }, "Explore from here"),
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
              e.happens ? h("span", { className: "sm-muted" }, " · " + when(e.happens)) : null));
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
        h("div", { className: "sm-fact-text" }, sentence(f.fact), f.happens ? h("span", { className: "sm-muted" }, " · " + when(f.happens)) : null),
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
    if (f.indexOf("thought") >= 0) return who(w.speaker) + " · own thought";
    if (f.indexOf("event") >= 0) return "System notice";
    if (f.indexOf("caption") >= 0) return "Image description (vision model)";
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
          h("div", { className: "sm-page-meta" }, [d.role !== "thing" ? roleLabel(d.role, true) : null, d.fact_count + " fact" + (d.fact_count === 1 ? "" : "s"), d.mentions.length + (d.mentions.length >= 60 ? "+" : "") + " mentions",
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
              var inner = [h("span", { key: "n", className: "sm-linked-name" }, l.name), h("span", { key: "r", className: "sm-muted" }, trunc((l.relations || [l.relation]).join(" · "), 80))];
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

  // ------------------------------------------------------------------ settings
  // Sophia's settings, read and saved through Hermes's memory-provider config API: the same fields and validation as
  // Plugins → Sophia in Hermes and `hermes memory setup`. Each field shows the value Sophia uses now.
  var SETTING_GROUPS = [["basics", "Basics", "Who's talking, the model server, and the three models"],
                        ["servers", "A server per job", "Shown when “Model servers” is per-job"],
                        ["advanced", "Tuning", "Recall, capture, the night and the dashboard's graph"]];
  function fieldGroup(f) {
    if (!f.when) return "basics";
    return f.when.server_layout ? "servers" : "advanced";
  }
  function SettingsView() {
    var ctx = useContext(Ctx);
    var st = useState({ fields: null, error: null }), cfg = st[0], setCfg = st[1];
    var valS = useState({}), values = valS[0], setValues = valS[1];
    var dirtyS = useState({}), dirty = dirtyS[0];
    var busy = useState(false);
    var qS = useState(""), q = qS[0];
    var load = useCallback(function () {
      if (!SDK.api || !SDK.api.getMemoryProviderConfig) { setCfg({ fields: null, error: "This Hermes version has no settings API for plugins." }); return; }
      SDK.api.getMemoryProviderConfig("sophia").then(function (r) {
        var v = {};
        (r.fields || []).forEach(function (f) { v[f.key] = f.value; });
        setCfg({ fields: r.fields || [], error: null }); setValues(v); dirtyS[1]({});
      }, function (e) { setCfg({ fields: null, error: errText(e) }); });
    }, []);
    useEffect(function () { load(); }, [load]);
    if (cfg.error) return h(Failed, { error: cfg.error, retry: load });
    if (!cfg.fields) return h(Loading);
    function visible(f) {
      if (!f.when) return true;
      return Object.keys(f.when).every(function (k) { return String(values[k]) === String(f.when[k]); });
    }
    function set(key, v) {
      setValues(function (o) { var n = Object.assign({}, o); n[key] = v; return n; });
      dirtyS[1](function (o) { var n = Object.assign({}, o); n[key] = true; return n; });
    }
    function save() {
      busy[1](true);
      var out = {};
      cfg.fields.forEach(function (f) { if (f.kind !== "secret" || values[f.key]) out[f.key] = values[f.key]; });
      SDK.api.updateMemoryProviderConfig("sophia", out).then(function () {
        busy[1](false); dirtyS[1]({});
        ctx.notify("Saved. New conversations and tonight's run use it; this dashboard already does.");
        ctx.changed(); load();
      }, function (e) { busy[1](false); ctx.notify("Couldn't save: " + errText(e)); });
    }
    var ql = q.trim().toLowerCase();
    var n = Object.keys(dirty).length;
    var input = function (f) {
      var v = values[f.key], id = "sm-set-" + f.key;
      if (f.kind === "select") {
        return h("select", { id: id, value: String(v), onChange: function (e) { set(f.key, e.target.value); } },
          f.options.map(function (o) { return h("option", { key: o.value, value: o.value }, o.label); }));
      }
      if (f.kind === "boolean") {
        return h("input", { id: id, type: "checkbox", checked: !!v, onChange: function (e) { set(f.key, e.target.checked); } });
      }
      var num = f.kind === "integer" || f.kind === "number";
      return h("input", { id: id, type: f.kind === "secret" ? "password" : num ? "number" : "text", value: v == null ? "" : String(v),
        min: f.minimum != null ? f.minimum : undefined, max: f.maximum != null ? f.maximum : undefined,
        step: f.step != null ? f.step : f.kind === "integer" ? 1 : num ? "any" : undefined, placeholder: f.placeholder || "",
        onChange: function (e) { set(f.key, num && e.target.value !== "" ? Number(e.target.value) : e.target.value); } });
    };
    return h("div", { className: "sm-settings" },
      h("div", { className: "sm-settings-head" },
        h("p", { className: "sm-hint" }, "The same settings as Plugins → Sophia in Hermes, and `hermes memory setup`. New conversations and the next night pick up a change; this dashboard does at once."),
        h("div", { className: "sm-search" }, h(Icon, { name: "search", size: 18 }),
          h("input", { type: "search", value: q, placeholder: "Find a setting…", "aria-label": "Find a setting", onChange: function (e) { qS[1](e.target.value); } }))),
      SETTING_GROUPS.map(function (g) {
        var fields = cfg.fields.filter(function (f) {
          return fieldGroup(f) === g[0] && (ql ? (f.key + " " + f.label + " " + f.description).toLowerCase().indexOf(ql) >= 0 : visible(f));
        });
        if (!fields.length) return null;
        return h("section", { key: g[0], className: "sm-card sm-settings-group", "aria-label": g[1] },
          h("div", { className: "sm-card-head" }, h("h2", { className: "sm-h2" }, g[1]), h("span", { className: "sm-card-aside sm-muted" }, g[2])),
          fields.map(function (f) {
            return h("div", { key: f.key, className: cx("sm-setting", dirty[f.key] && "sm-setting-dirty", !visible(f) && "sm-setting-hidden") },
              h("label", { htmlFor: "sm-set-" + f.key },
                h("span", { className: "sm-setting-name" }, f.label), h("code", { className: "sm-setting-key" }, f.key)),
              h("div", { className: "sm-setting-input" }, input(f)),
              f.description && h("p", { className: "sm-setting-desc" }, f.description),
              !visible(f) && h("p", { className: "sm-setting-desc sm-warn" }, "Not in use with the current choices above."));
          }));
      }),
      h("div", { className: "sm-settings-bar" },
        h("span", { className: "sm-muted" }, n ? n + " unsaved change" + (n === 1 ? "" : "s") : "No unsaved changes"),
        h(Btn, { onClick: load, disabled: !n || busy[0] }, "Discard"),
        h(Btn, { primary: true, onClick: save, disabled: !n || busy[0] }, "Save")));
  }

  // ------------------------------------------------------------------ corrections
  function CorrectSheet(p) {
    var t = p.target, ctx = useContext(Ctx);
    var opts = [];
    if (t.window && (!t.only || t.only === "relabel")) opts.push(["relabel", "Someone else said this", "Relabel who said the whole message. Facts already drawn from it don't change: retract any that are wrong."]);
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

  // ------------------------------------------------------------ continuity
  // The companion plugin, watched: why it's quiet, what it did today, what's waiting and why it pulls, what it held
  // back, and how much of each turn the standing view takes. Read-only; every profile with a continuity store can
  // be chosen (try it on a test profile first).
  var OUTCOME_TONE = { silent: "", held: "sm-amber", sent: "sm-ok", "not accepted": "sm-warn", "not started": "sm-warn",
                       interrupted: "", failed: "sm-warn", running: "" };
  function ContinuityView() {
    var profS = useState(""), prof = profS[0];
    var api = useApi("/continuity" + (prof ? "?profile=" + encodeURIComponent(prof) : ""), 10000);
    var d = api.data;
    if (!d) return h(Card, { title: "Continuity" }, h(Empty, null, api.error ? "Couldn't load: " + api.error : "Loading…"));
    if (!d.report || !d.report.exists) return h(Card, { title: "Continuity" },
      h("p", { className: "sm-lede" }, "The continuity companion hasn't run on any profile yet."),
      h("p", { className: "sm-hint" }, "It lets the agent keep going between messages: what it perceives and what comes to mind start turns of its own, and an energy budget winds them down. Try it on a test profile first (docs/CONTINUITY.md, “Trying it”)."));
    var r = d.report, t = r.today, q = r.quiet, u = r.user;
    var picker = d.profiles.length > 1 ? h(Seg, { label: "Profile", caption: "Profile", value: d.profile,
      options: d.profiles.map(function (n) { return [n, n]; }), onChange: profS[1] }) :
      h("span", { className: "sm-tag" }, "profile: " + d.profile);
    var energyPct = Math.min(1, r.energy / Math.max(r.settings.energy_max || 3, 0.01));
    var outcomes = Object.keys(t.outcomes || {}).sort(function (a, b) { return t.outcomes[b] - t.outcomes[a]; });

    var now = h(Card, { title: "Right now", aside: picker },
      h("div", { className: "sm-now-grid" },
        h("div", { className: "sm-now-cell" }, h("span", { className: "sm-now-label" }, "Energy"),
          h("span", { className: "sm-now-big" }, r.energy.toFixed(2)),
          h("div", { className: "sm-gate-bar", title: "a turn of its own costs " + r.step_cost },
            h("span", { style: { width: pct(energyPct), background: "var(--sm-cyan)" } }),
            h("span", { className: "sm-gate-cut", style: { left: pct(r.step_cost / (r.settings.energy_max || 3)) } })),
          h("span", { className: "sm-now-sub" }, "a turn costs " + r.step_cost)),
        h("div", { className: "sm-now-cell" }, h("span", { className: "sm-now-label" }, r.paused ? "Paused" : q.reason ? "Quiet" : "Ready"),
          h("span", { className: "sm-now-sub" }, r.paused ? "It won't take turns of its own until resumed." :
            (q.reason || "ready: it takes a turn of its own when something it perceives or remembers pulls hard enough")),
          q.kind && h("span", { className: cx("sm-badge", q.kind === "healthy" ? "sm-ok" : "sm-warn") },
            q.kind === "healthy" ? "the right kind of quiet" : "stalled: worth a look"),
          q.since && h("span", { className: "sm-now-sub" }, "since " + q.since)),
        h("div", { className: "sm-now-cell" }, h("span", { className: "sm-now-label" }, u.name),
          h("span", { className: "sm-now-sub" }, u.last_wrote ? "last wrote " + u.ago : "hasn't written yet"),
          h("span", { className: cx("sm-badge", u.around ? "sm-ok" : "") }, u.around ? "around" : "not around"),
          h("span", { className: "sm-now-sub" }, "held messages go out only when allowed and " + u.name + " is around")),
        h("div", { className: "sm-now-cell" }, h("span", { className: "sm-now-label" }, "Outreach"),
          h("span", { className: "sm-now-big" }, t.outreach),
          h("span", { className: "sm-now-sub" }, t.outreach_sent + " of " + t.outreach_limit + " sent today · quiet hours " + t.quiet_hours))));

    var today = h(Card, { title: "Today", aside: h("span", { className: "sm-muted" }, t.model_seconds + " s of model time") },
      h("div", { className: "sm-stats" },
        h("div", { className: "sm-stat" }, h("span", { className: "sm-stat-n" }, t.turns + "/" + t.budget), h("span", { className: "sm-stat-l" }, "turns of its own")),
        outcomes.map(function (k) {
          return h("div", { key: k, className: "sm-stat" }, h("span", { className: cx("sm-stat-n", OUTCOME_TONE[k]) }, t.outcomes[k]),
            h("span", { className: "sm-stat-l" }, k));
        })),
      h("p", { className: "sm-hint" }, "All silent: it's doing nothing. All held: outreach is off or it's quiet hours. Any “not accepted” or “not started”: a stall to chase."));

    var queue = h(Card, { title: "Waiting to come to mind", count: r.queue.waiting, plainCount: true },
      r.queue.top.length ? h("div", { className: "sm-lines" }, r.queue.top.map(function (it) {
        var w = it.why || {};
        return h("div", { key: it.id, className: "sm-line-item" },
          h("div", { className: "sm-q-title" }, "“" + trunc(it.text, 180) + "”"),
          h("div", { className: "sm-gate-bar", title: "pull " + it.pull + "; a turn needs " + r.min_pull },
            h("span", { style: { width: pct(Math.min(1, it.pull)), background: it.clears_threshold ? "var(--sm-cyan)" : "var(--sm-muted)" } }),
            h("span", { className: "sm-gate-cut", style: { left: pct(r.min_pull) } })),
          h("div", { className: "sm-chips-row" },
            h("span", { className: "sm-chip" }, "pull " + it.pull + (it.clears_threshold ? "" : " (below)")),
            h("span", { className: "sm-chip" }, "depth " + it.depth),
            h("span", { className: "sm-chip" }, it.age_min + " min old, fades in " + it.fades_in_min),
            it.superseded && h("span", { className: "sm-badge sm-amber", title: (it.changed || []).join("; ") }, "superseded"),
            w.similarity != null && h("span", { className: "sm-tag" }, "similarity " + w.similarity),
            w.recently_raised ? h("span", { className: "sm-tag" }, "recently raised " + w.recently_raised) : null,
            w.chain_factor != null && w.chain_factor < 1 && h("span", { className: "sm-tag" }, "chain ×" + w.chain_factor),
            it.via && h("span", { className: "sm-tag" }, it.via)));
      })) : h(Empty, null, "Nothing waiting."));

    var ws = r.working_state;
    var state = h(Card, { title: "Working state" },
      h("div", { className: "sm-lines" },
        h("div", null, h("span", { className: "sm-muted" }, "Focus: "), ws.focus || "nothing in particular"),
        h("div", null, h("span", { className: "sm-muted" }, "Open threads: "), ws.threads.length ? ws.threads.join("; ") : "none"),
        h("div", null, h("span", { className: "sm-muted" }, "Waiting for: "), ws.waiting_for.length ? ws.waiting_for.join("; ") : "nothing"),
        h("div", null, h("span", { className: "sm-muted" }, "Came to mind lately: "),
          ws.came_to_mind.length ? ws.came_to_mind.map(function (m) { return "“" + trunc(m.text, 80) + "”"; }).join(" · ") : "nothing")));

    var outbox = h(Card, { title: "Held for " + u.name, count: r.outbox.held.length, plainCount: true },
      r.outbox.held.length ? h("div", { className: "sm-lines" }, r.outbox.held.map(function (m) {
        return h("div", { key: m.id, className: "sm-line-item" },
          h("div", { className: "sm-ch-meta" }, m.created + " · " + m.reason), h("div", { className: "sm-quote" }, m.text));
      })) : h(Empty, null, "Nothing held."));

    var journal = h(Card, { title: "Journal" },
      r.journal.length ? h("div", { className: "sm-feed-list" }, r.journal.map(function (j, i) {
        if (j.what === "quiet") return h("div", { key: i, className: "sm-feed-row" },
          h("span", { className: cx("sm-badge", j.kind === "healthy" ? "sm-ok" : "sm-warn") }, "quiet"),
          h("span", { className: "sm-feed-t" }, j.at.slice(11)),
          h("span", null, j.reason + " — " + j.turns + " turns: " + j.silent + " silent, " + j.held + " held; " + j.model_seconds + " s"));
        return h("div", { key: i, className: "sm-feed-row" },
          h("span", { className: cx("sm-badge", OUTCOME_TONE[j.outcome]) }, j.outcome),
          h("span", { className: "sm-feed-t" }, j.at.slice(11)),
          h("span", null, trunc(j.item, 140) + " · " + j.seconds + " s" + (j.reason ? " · " + j.reason : "")));
      })) : h(Empty, null, "No turns of its own yet."));

    var f = r.frames;
    var frames = h(Card, { title: "Standing view", aside: h("span", { className: "sm-muted" }, "full every " + f.full_every + " turns") },
      h("div", { className: "sm-stats" },
        Object.keys(f.kinds || {}).map(function (k) {
          return h("div", { key: k, className: "sm-stat" }, h("span", { className: "sm-stat-n" }, f.kinds[k]), h("span", { className: "sm-stat-l" }, k + " frames"));
        }),
        h("div", { className: "sm-stat" }, h("span", { className: "sm-stat-n" }, f.mean_fill != null ? pct(f.mean_fill) : "–"),
          h("span", { className: "sm-stat-l" }, "of each turn's context, mean")),
        h("div", { className: "sm-stat" }, h("span", { className: "sm-stat-n" }, f.max_fill != null ? pct(f.max_fill) : "–"),
          h("span", { className: "sm-stat-l" }, "max"))),
      f.latest && h("pre", { className: "sm-mono sm-frame" }, f.latest),
      f.latest_full && f.latest_full !== f.latest && h("details", null, h("summary", { className: "sm-muted" }, "Latest full frame"),
        h("pre", { className: "sm-mono sm-frame" }, f.latest_full)));

    return h("div", { className: "sm-overview" }, now, today, queue, state, outbox, journal, frames);
  }

  function SophiaTab() {
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
    if (missing && route.view !== "settings" && route.view !== "continuity") body = h(Card, { title: "No memory here yet" }, h("p", { className: "sm-lede" }, now.error),
      h("p", { className: "sm-hint" }, "This tab reads Sophia's store for the active profile. Set memory.provider to sophia and talk for a while."));
    else if (route.view === "graph") body = h(GraphView, { arg: route.arg, go: go, wide: wide, key: "graph" });
    else if (route.view === "pages") body = h(PagesView, { arg: route.arg, go: go, wide: wide });
    else if (route.view === "recall") body = h(RecallView, { arg: route.arg, go: go, wide: wide });
    else if (route.view === "settings") body = h(SettingsView, null);
    else if (route.view === "continuity") body = h(ContinuityView, null);
    else body = h(Overview, { now: now.data, go: go });

    var tab = function (v, cls) {
      var on = route.view === v[0];
      return h("a", { key: v[0], href: routeHref(v[0], ""), className: cx(cls, on && "sm-on"), "aria-current": on ? "page" : undefined,
        onClick: function (e) { e.preventDefault(); go(v[0]); } }, h(Icon, { name: v[2], size: cls === "sm-tabbar-item" ? 22 : 18 }), h("span", null, v[1]));
    };
    return h(Ctx.Provider, { value: ctx },
      h("div", { className: cx("sm", wide ? "sm-wide" : "sm-narrow") },
        h("header", { className: "sm-top" },
          wide && h("h1", { className: "sm-title" }, "Sophia"),
          wide && h("nav", { className: "sm-tabs", "aria-label": "Sophia views" }, VIEWS.map(function (v) { return tab(v, "sm-tab"); })),
          h(LivePill, { now: now.data, onClick: function () { go("overview"); } })),
        h("main", { className: "sm-body" }, body),
        !wide && h("nav", { className: "sm-tabbar", "aria-label": "Sophia views" }, VIEWS.map(function (v) { return tab(v, "sm-tabbar-item"); })),
        fixS[0] && h(CorrectSheet, { target: fixS[0], close: function () { fixS[1](null); } }),
        toast && h("div", { className: "sm-toast", role: "status" }, h("span", null, toast.msg),
          toast.undoId ? h(Btn, { small: true, onClick: function () { var id = toast.undoId; setToast(null); ctx.undo(id); } }, "Undo") : null)));
  }

  window.__HERMES_PLUGINS__.register("sophia", SophiaTab);
})();
