/* JFC Post-Event Recap Dashboard - front end. Talks to /api/data. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => (n == null ? "" : "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const fmtDate = (s) => {
    if (!s) return "";
    const d = new Date(s.length === 10 ? s + "T12:00:00" : s);
    return isNaN(d) ? s : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };
  const fmtDateTime = (s) => {
    if (!s) return "";
    const d = new Date(s);
    return isNaN(d) ? s : d.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  };
  const isUrl = (s) => /^https?:\/\//i.test(String(s || "").trim());

  let DATA = null;
  let fy = null;
  let open = null; // {type:'bill'|'rso', id}
  let timer = null;
  const byBill = new Map(), byRso = new Map(), byRecap = new Map();

  // ---------- badges ----------
  function strikeBadge(level, opts = {}) {
    const lv = DATA.levels[Math.min(level, 3)];
    const dots = [1, 2, 3].map((i) => `<i class="${i <= level ? "on" : ""}"></i>`).join("");
    const text = opts.long ? lv.label : lv.short;
    return `<span class="pill c-${lv.color}" title="${esc(lv.label)}">${esc(text)}<span class="strike-dots">${dots}</span></span>`;
  }
  function rsoRecord(r) {
    if (!r) return `<span class="sub">RSO not found</span>`;
    const c = (k) => r.counts[k] || 0;
    const good = c("on_time") + c("submitted_no_date") + c("waived");
    const bad = c("late") + c("missing") + c("not_tracked");
    const unk = c("no_date");
    return `${strikeBadge(r.level.level)}<div class="sub">${good} on time · ${c("late")} late · ${c("missing")} missing · ${c("not_tracked")} not tracked · ${c("pending")} due soon · ${unk} no recap yet</div>`;
  }
  const recapPill = (b) => b.in_queue && b.recap_status === "not_funded"
    ? `<span class="pill c-blue">In review, recap due after the event</span>`
    : `<span class="pill c-${b.recap_color}">${esc(b.recap_status_label)}</span>`;

  function recapDetail(b) {
    if (b.recap_status === "pending") return `Due ${fmtDate(b.due_date)} (${b.days_until_due} day${b.days_until_due === 1 ? "" : "s"} left)`;
    if (b.recap_status === "missing") return `Was due ${fmtDate(b.due_date)}, ${b.days_overdue} days overdue`;
    if (b.recap_status === "late" || b.recap_status === "on_time") return `Submitted ${fmtDate(b.submitted_recap_at)}`;
    if (b.recap_status === "upcoming") return `Due ${fmtDate(b.due_date)}`;
    if (b.recap_status === "no_date") return b.days_since_submitted != null ? `Bill submitted ${b.days_since_submitted} days ago` : "";
    return "";
  }

  // ---------- data ----------
  const DEMO = window.__DEMO_DATA__ || null;
  async function load(force = false) {
    if (DEMO) {
      DATA = DEMO;
      index(); render();
      return;
    }
    const q = new URLSearchParams();
    if (fy) q.set("fy", fy);
    if (force) q.set("refresh", "1");
    try {
      const res = await fetch("/api/data?" + q.toString(), { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      DATA = data;
      index();
      render();
      $("#errorBanner").hidden = !data.error;
      if (data.error) $("#errorBanner").textContent = "Couldn't reload the data, showing the last good copy. " + data.error;
    } catch (e) {
      $("#errorBanner").hidden = false;
      $("#errorBanner").textContent = "Couldn't load data: " + e.message;
    }
    clearTimeout(timer);
    timer = setTimeout(load, ((DATA && DATA.refresh_seconds) || 60) * 1000);
  }

  function index() {
    byBill.clear(); byRso.clear(); byRecap.clear();
    DATA.bills.forEach((b) => byBill.set(b.bill_number, b));
    DATA.rsos.forEach((r) => byRso.set(r.key, r));
    DATA.recaps.forEach((r) => byRecap.set(r.id, r));
  }

  // ---------- render ----------
  function render() {
    $("#updated").textContent = `Data loaded ${DATA.loaded_at}`;
    const sel = $("#fySelect");
    const cur = DATA.current_fiscal_year;
    const want = [cur - 1, cur, cur + 1];
    sel.innerHTML = want.map((y) => `<option value="${y}" ${y === DATA.fiscal_year ? "selected" : ""}>FY${String(y).slice(2)} (Jul ${y - 1} to Jun ${y})</option>`).join("");

    const unm = DATA.columns.bills_unmapped;
    const mb = $("#mappingBanner");
    if (DATA.warnings && DATA.warnings.length) {
      mb.hidden = false;
      mb.textContent = DATA.warnings.join(" ");
    } else if (!DATA.bills.length) {
      mb.hidden = false;
      mb.textContent = "No bills sheet loaded, so only recap submissions are shown. Point bills_source in config.json at the master bills sheet to see missing recaps and strikes.";
    } else if (unm.includes("event_date")) {
      mb.hidden = false;
      mb.textContent = "The bills sheet has no column mapped to event_date, so recap deadlines (14 days after the event) can't be checked. Add your column name under bill_columns.event_date in config.json.";
    } else mb.hidden = true;

    if (!render.done) {
      render.done = true;
      if (DATA.bills.some((b) => b.in_queue)) $("#billQueue").value = "queue";
    }
    renderStats();
    const statuses = [...new Set(DATA.bills.map((b) => b.recap_status))];
    const bs = $("#billStatus"), keep = bs.value;
    bs.innerHTML = `<option value="">All recap statuses</option>` + statuses.map((s) => `<option value="${s}">${esc(DATA.recap_statuses[s].label)}</option>`).join("");
    bs.value = keep;
    renderBills(); renderRsos(); renderFlags(); renderRules();
    $("#flagCount").textContent = DATA.flags.length || "";
    if (open) openDrawer(open.type, open.id, true);
    if (DEMO) { $("#refreshBtn").hidden = true; $("#fySelect").disabled = true; $("#updated").textContent = `Demo snapshot · data as of ${fmtDate(DATA.today)}`; }
    renderSetup();
  }

  function renderStats() {
    const lv = [0, 0, 0, 0];
    DATA.rsos.forEach((r) => lv[r.level.level]++);
    const missing = DATA.bills.filter((b) => b.recap_status === "missing").length;
    const pending = DATA.bills.filter((b) => b.recap_status === "pending").length;
    const card = (n, l, cls = "", act = "") => `<div class="stat ${act ? "clickable" : ""}" ${act}><div class="n ${cls}">${n}</div><div class="l">${l}</div></div>`;
    $("#stats").innerHTML = [
      card(DATA.bills.filter((b) => b.in_queue).length, "Bills in review queue", "", `data-go="bills" data-queue="queue"`),
      card(DATA.bills.filter((b) => b.in_queue && b.rso_level > 0).length, "Queued bills from RSOs with strikes", "", `data-go="bills" data-queue="queue" data-hold="1"`),
      card(DATA.recaps.length, "Recap forms submitted"),
      card(missing, "Recaps overdue", "", `data-go="bills" data-status="missing"`),
      card(DATA.bills.filter((b) => b.recap_status === "no_date").length, "Approved event bills with no recap yet (event date unknown)", "", `data-go="bills" data-status="no_date"`),
      card(pending, "Recaps due soon", "", `data-go="bills" data-status="pending"`),
      `<div class="stat"><div class="n">${lv[1] + lv[2] + lv[3]}</div><div class="l strike-tiles">RSOs with strikes:
        <button class="pill c-yellow" data-lv="1">${lv[1]} × Strike 1</button>
        <button class="pill c-orange" data-lv="2">${lv[2]} × Strike 2</button>
        <button class="pill c-red" data-lv="3">${lv[3]} × Strike 3</button></div></div>`,
    ].join("");
    $$("#stats [data-lv]").forEach((el) => el.addEventListener("click", () => {
      $("#rsoLevel").value = el.dataset.lv; renderRsos(); showTab("rsos");
    }));
    $$("#stats .clickable").forEach((el) => el.addEventListener("click", () => {
      const go = el.dataset.go;
      if (go === "bills") { $("#billStatus").value = el.dataset.status || ""; $("#billLevel").value = el.dataset.hold ? "hold" : ""; $("#billQueue").value = el.dataset.queue || "recap"; renderBills(); }
      if (go === "rsos") { $("#rsoLevel").value = el.dataset.level || ""; renderRsos(); }
      showTab(go);
    }));
  }

  function renderBills() {
    const q = $("#billSearch").value.trim().toLowerCase();
    const st = $("#billStatus").value, lvl = $("#billLevel").value, qv = $("#billQueue").value;
    const all = DATA.bills.filter((b) =>
      (!qv || (qv === "queue" ? b.in_queue : b.requires_recap)) &&
      (!q || [b.bill_number, b.rso, b.title].join(" ").toLowerCase().includes(q)) &&
      (!st || b.recap_status === st) && (lvl === "" || (lvl === "hold" ? b.rso_level > 0 : String(Math.min(b.rso_level, 3)) === lvl)));
    const rows = all.slice(0, 400);
    $("#billsMore").hidden = all.length <= rows.length;
    $("#billsMore").textContent = `Showing the first ${rows.length} of ${all.length} bills. Search or filter to narrow it down.`;
    $("#billsTable tbody").innerHTML = rows.map((b) => `
      <tr data-bill="${esc(b.bill_number)}">
        <td class="mono">${esc(b.bill_number)}</td>
        <td>${esc(b.rso)}<div>${strikeBadge(b.rso_level)} ${b.in_queue ? (`<span class="pill c-blue">In review queue</span>`) : ""}</div></td>
        <td>${esc(b.title || "")}${b.flags.length ? ` <span class="pill c-orange" title="${esc(b.flags.join("; "))}">flag</span>` : ""}<div class="sub">${esc(b.status || "")}${b.category ? " · " + esc(b.category) : ""}</div></td>
        <td>${fmtDate(b.event_date)}</td>
        <td>${b.in_queue && !b.requires_recap ? rsoRecord(byRso.get(b.rso_key)) : `${recapPill(b)}<div class="sub">${recapDetail(b)}</div>`}</td>
        <td class="num">${money(b.amount_approved ?? b.amount_requested)}</td>
      </tr>`).join("");
    $("#billsEmpty").hidden = rows.length > 0;
  }

  function renderRsos() {
    const q = $("#rsoSearch").value.trim().toLowerCase();
    const lvl = $("#rsoLevel").value;
    const rows = DATA.rsos.filter((r) =>
      (!q || (r.name + " " + r.aliases.join(" ")).toLowerCase().includes(q)) &&
      (lvl === "" || String(r.level.level) === lvl));
    $("#rsoTable tbody").innerHTML = rows.map((r) => `
      <tr data-rso="${esc(r.key)}">
        <td>${esc(r.name)}</td>
        <td>${strikeBadge(r.level.level)}</td>
        <td class="num">${r.bill_count}</td>
        <td class="num">${(r.counts.on_time || 0) + (r.counts.submitted_no_date || 0)}</td>
        <td class="num">${r.counts.late || 0}</td>
        <td class="num">${r.counts.missing || 0}</td>
        <td class="num">${r.counts.not_tracked || 0}</td>
        <td class="num">${r.counts.pending || 0}</td>
        <td class="num">${r.counts.no_date || 0}</td>
        <td class="num">${money(r.total_approved)}</td>
        <td>${fmtDate(r.last_recap_at)}</td>
      </tr>`).join("");
    $("#rsoEmpty").hidden = rows.length > 0;
  }

  function renderFlags() {
    if (!DATA.flags.length) { $("#flagList").innerHTML = `<p class="empty">Nothing to review.</p>`; return; }
    $("#flagList").innerHTML = DATA.flags.map((f) => {
      const head = f.type === "bill" ? `Bill <span class="mono">${esc(f.bill_number)}</span> · ${esc(f.rso)}` : `Recap form #${esc(f.recap_id)} · ${esc(f.rso)}`;
      const attr = f.type === "bill" ? `data-bill="${esc(f.bill_number)}"` : `data-rso="${esc(f.rso_key)}"`;
      return `<div class="flag clickable" ${attr}><strong>${head}</strong><div>${f.problems.map(esc).join("<br>")}</div></div>`;
    }).join("");
  }

  function renderRules() {
    const c = DATA.citations;
    $("#rules").innerHTML = `
      <p>Strikes are worked out automatically from the bills sheet and the recap form, using these rules. JFC can waive or add a strike in <span class="mono">strike_adjustments.csv</span>.</p>
      <h3>${esc(c.requirement.section)}</h3><blockquote>${esc(c.requirement.text)}</blockquote>
      <h3>${esc(c.noncompliance.section)}</h3><blockquote>${esc(c.noncompliance.text)}</blockquote>
      <p>${DATA.levels.map((l) => strikeBadge(l.level)).join(" ")}</p>
      <blockquote>${esc(c.not_tracked.text)}</blockquote>
      <blockquote>${esc(c.reset.text)} ${esc(c.fiscal_year.text)}</blockquote>
      <h3>${esc(c.joint.section)}</h3><blockquote>${esc(c.joint.text)}</blockquote>
      <h3>${esc(c.allowable.section)}</h3><blockquote>${esc(c.allowable.text)}</blockquote>
      <h3>How the dashboard decides</h3>
      <ul>
        <li>Recap deadline = event date + 14 days. A recap counts for a bill when the bill number appears in the form's Bill/Budget Number answer.</li>
        <li><strong>Missing</strong>: no recap and the deadline has passed. <strong>Late</strong>: first recap came in after the deadline. Both are strikes.</li>
        <li><strong>Attendance not tracked</strong>: the recap has no readable attendance number or no proof of attendance. This is a strike even though the form was sent.</li>
        <li>Strikes count within the selected fiscal year (July 1 to June 30) and are numbered by date.</li>
        <li>Only bills whose status is in <span class="mono">rules.statuses_requiring_recap</span> (config.json) need a recap.</li>
      </ul>`;
  }

  function renderSetup() {
    const el = $("#setup");
    if (!el) return;
    const base = location.origin && location.origin.startsWith("http") ? location.origin + location.pathname : "http://localhost:8000/";
    const code = `javascript:(()=>{const m=location.href.match(/edit\\/(\\d+)/)||location.href.match(/(\\d{6})/);if(!m){alert('Open a bill in Engage first, then click this.');return;}window.open('${base}#bill='+m[1],'jfcrecap');})()`;
    el.innerHTML = `
      <h3>From Engage: one-click check</h3>
      <p>Drag this button to your browser's bookmarks bar:</p>
      ${DEMO ? '<p class="flag">This is a demo snapshot. The Engage button works with the installed dashboard (see the README), where it opens the bill you are looking at.</p>' : ''}
      <p><a class="btn" href="${esc(code)}" onclick="alert('Drag me to the bookmarks bar instead of clicking.');return false;">JFC recap check</a></p>
      <p>Then, while you have a bill open in Engage (a page like <span class="mono">gatech.campuslabs.com/engage/budgeting/reviews#/edit/395191</span>), click the bookmark. This dashboard opens on that bill, with the RSO's strikes and recap history.</p>
      <h3>In Excel</h3>
      <p>The repo includes <span class="mono">excel/RecapStrikeCheck.ts</span>, an Office Script. Add it once to the JFC Data Sheet (Automate tab), paste the Post-Event Recap Form responses into a sheet named <span class="mono">Recap Responses</span>, and run it. It writes a <span class="mono">Recap Check</span> sheet with the same statuses and color-coded strikes as this dashboard. Step-by-step instructions are in the README.</p>
      <h3>Data</h3>
      <p class="sub">${(DATA.sources || []).map(esc).join("<br>")}</p>`;
  }

  // ---------- drawer ----------
  function heroFor(r) {
    const lv = r.level;
    return `<div class="hero c-${lv.color}"><div class="big">${lv.level ? `This RSO is on ${esc(lv.label)}` : "No strikes"}${lv.count > 3 ? ` (${lv.count} strikes recorded)` : ""}</div>
      <div class="cite">FY${String(DATA.fiscal_year).slice(2)} · SAF Policy §9.5.2</div></div>`;
  }

  function recapCard(rc) {
    const a = rc.attendance;
    const att = a.total == null ? esc(a.raw || "Not given") :
      `${a.total} total` + (a.gt != null ? ` · ${a.gt} GT` : "") + (a.non_gt != null ? ` · ${a.non_gt} non-GT` : "") + ` <span class="sub">(“${esc(a.raw)}”)</span>`;
    return `<div class="recap-card">
      <dl class="kv">
        <dt>Submitted</dt><dd>${fmtDateTime(rc.submitted_at)} by ${esc(rc.name || "")} ${rc.email ? `<span class="sub">${esc(rc.email)}</span>` : ""}</dd>
        <dt>Event</dt><dd>${esc(rc.event_name || "")}</dd>
        <dt>Date and location</dt><dd>${esc(rc.event_date_location || "")}</dd>
        <dt>Bill numbers given</dt><dd class="mono">${esc(rc.bill_raw || "")}</dd>
        <dt>Attendees</dt><dd>${att}</dd>
        <dt>Proof of attendance</dt><dd>${rc.has_proof ? (isUrl(rc.proof) ? `<a href="${esc(rc.proof)}" target="_blank" rel="noopener">Open proof</a>` : esc(rc.proof)) : `<span class="pill c-red">None</span>`}</dd>
        <dt>Summary and fund use</dt><dd>${esc(rc.summary || "")}</dd>
      </dl>
      ${rc.problems.length ? rc.problems.map((p) => `<div class="flag">${esc(p)}</div>`).join("") : ""}
    </div>`;
  }

  function billDrawer(b) {
    const r = byRso.get(b.rso_key);
    const recs = b.recap_ids.map((id) => byRecap.get(id)).filter(Boolean);
    const others = r ? r.bill_numbers.filter((n) => n !== b.bill_number).map((n) => byBill.get(n)).filter(Boolean) : [];
    const ratio = b.attendance_ratio != null ? ` (${Math.round(b.attendance_ratio * 100)}% of expected)` : "";
    return `
      <div class="sub">Bill <span class="mono">${esc(b.bill_number)}</span>${b.status ? " · " + esc(b.status) : ""}</div>
      <h2>${esc(b.title || "Bill " + b.bill_number)}</h2>
      <div><a href="#" data-rso="${esc(b.rso_key)}">${esc(b.rso)}</a></div>
      ${r ? heroFor(r) : ""}
      ${b.in_queue && r ? `<h3>This RSO's recap record</h3><div>${rsoRecord(r)}</div>` : ""}
      <h3>Post-event recap for this bill</h3>
      <div>${recapPill(b)} <span class="sub">${recapDetail(b)}</span></div>
      ${b.waiver ? `<div class="flag">Strike waived by JFC: ${esc(b.waiver)} (was: ${esc(DATA.recap_statuses[b.original_status].label)})</div>` : ""}
      ${b.flags.map((f) => `<div class="flag">${esc(f)}</div>`).join("")}
      <dl class="kv" style="margin-top:10px">
        ${b.in_queue ? `<dt>Review</dt><dd><span class="pill c-blue">In JFC review queue</span>${b.review_step ? " " + esc(b.review_step) : ""}</dd>` : ""}
        ${b.submitter ? `<dt>Submitted by</dt><dd>${esc(b.submitter)}${b.submitted_date ? " on " + fmtDate(b.submitted_date) : ""}</dd>` : ""}
        ${b.category ? `<dt>Type</dt><dd>${esc(b.category)}</dd>` : ""}
        <dt>Event date</dt><dd>${fmtDate(b.event_date) || "<span class='sub'>Unknown</span>"}${b.event_date_source === "recap form" ? " <span class='sub'>(from the recap form)</span>" : ""}</dd>
        ${b.says_recaps_submitted ? `<dt>Said all recaps were in?</dt><dd>${esc(b.says_recaps_submitted)} <span class="sub">(bill form Q3)</span></dd>` : ""}
        <dt>Recap due</dt><dd>${fmtDate(b.due_date)}</dd>
        <dt>Requested / approved</dt><dd>${money(b.amount_requested) || "?"} / ${money(b.amount_approved) || "?"}</dd>
        <dt>Expected attendance</dt><dd>${b.expected_attendance ?? "<span class='sub'>Not in bills sheet</span>"}</dd>
        <dt>Actual attendance</dt><dd>${b.actual_attendance ?? "<span class='sub'>No recap yet</span>"}${ratio}</dd>
        ${b.cost_per_attendee != null ? `<dt>Cost per attendee</dt><dd>${money(b.cost_per_attendee)}</dd>` : ""}
      </dl>
      <div class="actions">${b.engage_url ? `<a class="btn" href="${esc(b.engage_url)}" target="_blank" rel="noopener">Open in Engage</a>` : ""}
        <button class="btn ghost" data-rso="${esc(b.rso_key)}">See all of this RSO's bills</button></div>
      ${recs.length ? `<h3>Recap form${recs.length > 1 ? "s" : ""} submitted</h3>${recs.map(recapCard).join("")}` : ""}
      ${r && r.strikes.length ? `<h3>Strikes this fiscal year</h3>${strikeList(r)}` : ""}
      ${others.length ? `<h3>Other bills from ${esc(b.rso)}</h3>${miniBills(others.slice(0, 8))}` : ""}`;
  }

  function strikeList(r) {
    return `<ul class="timeline">${r.strikes.map((s) => {
      const lv = DATA.levels[Math.min(s.number, 3)];
      return `<li><span class="pill c-${lv.color}">Strike ${s.number}</span><div>${esc(s.reason)}${s.bill_number ? ` · bill <a href="#" class="mono" data-bill="${esc(s.bill_number)}">${esc(s.bill_number)}</a>` : ""}${s.title ? ` (${esc(s.title)})` : ""}
        <div class="sub">${fmtDate(s.date)}${s.manual ? " · added by JFC" : ""}${s.resolved_on && !s.manual ? " · recap received " + fmtDate(s.resolved_on) : ""}</div></div></li>`;
    }).join("")}</ul>`;
  }

  function miniBills(list) {
    return `<div class="table-wrap"><table><thead><tr><th>Bill #</th><th>Event</th><th>Date</th><th>Recap</th></tr></thead><tbody>${list.map((b) => `
      <tr data-bill="${esc(b.bill_number)}"><td class="mono">${esc(b.bill_number)}</td><td>${esc(b.title || "")}</td><td>${fmtDate(b.event_date)}</td><td>${recapPill(b)}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function rsoDrawer(r) {
    const bills = r.bill_numbers.map((n) => byBill.get(n)).filter(Boolean);
    const recs = r.recap_ids.map((id) => byRecap.get(id)).filter(Boolean);
    const unmatched = recs.filter((rc) => !rc.matched_bills.length);
    const cnt = (k) => r.counts[k] || 0;
    return `
      <div class="sub">RSO${r.aliases.length ? " · also appears as " + r.aliases.map(esc).join(", ") : ""}</div>
      <h2>${esc(r.name)}</h2>
      ${heroFor(r)}
      <div class="stats" style="margin:12px 0">
        <div class="stat"><div class="n">${r.compliance_rate == null ? "–" : Math.round(r.compliance_rate * 100) + "%"}</div><div class="l">Recaps on time</div></div>
        <div class="stat"><div class="n">${cnt("on_time") + cnt("submitted_no_date")}</div><div class="l">On time</div></div>
        <div class="stat"><div class="n">${cnt("late")}</div><div class="l">Late</div></div>
        <div class="stat"><div class="n">${cnt("missing")}</div><div class="l">Missing</div></div>
        <div class="stat"><div class="n">${cnt("not_tracked")}</div><div class="l">Attendance not tracked</div></div>
        <div class="stat"><div class="n">${cnt("pending")}</div><div class="l">Due soon</div></div>
        <div class="stat"><div class="n">${cnt("no_date")}</div><div class="l">No recap yet (date unknown)</div></div>
        <div class="stat"><div class="n">${money(r.total_approved)}</div><div class="l">Approved (sheet)</div></div>
      </div>
      <h3>Strikes this fiscal year</h3>
      ${r.strikes.length ? strikeList(r) : `<p class="sub">No strikes in FY${String(DATA.fiscal_year).slice(2)}.</p>`}
      <h3>Bills and their recaps</h3>
      ${bills.length ? miniBills(bills) : `<p class="sub">No bills for this RSO in the bills sheet.</p>`}
      ${unmatched.length ? `<h3>Recap forms not matched to a bill</h3>${unmatched.map(recapCard).join("")}` : ""}
      <h3>All recap forms submitted (${recs.length})</h3>
      ${recs.length ? recs.map(recapCard).join("") : `<p class="sub">This RSO has not submitted any recap forms.</p>`}
      ${r.contacts.length ? `<h3>People who submitted recaps</h3><p>${r.contacts.map(esc).join("<br>")}</p>` : ""}`;
  }

  function openDrawer(type, id, silent = false) {
    const item = type === "bill" ? byBill.get(id) : byRso.get(id);
    if (!item) { open = null; $("#drawer").hidden = true; $("#drawerBackdrop").hidden = true; return; }
    open = { type, id };
    const body = $("#drawerBody");
    const scroll = $("#drawer").scrollTop;
    body.innerHTML = type === "bill" ? billDrawer(item) : rsoDrawer(item);
    $("#drawer").hidden = false; $("#drawerBackdrop").hidden = false;
    if (silent) $("#drawer").scrollTop = scroll; else $("#drawer").scrollTop = 0;
    const hash = `#${type}=${encodeURIComponent(id)}`;
    if (!DEMO && location.hash !== hash) { try { history.replaceState(null, "", hash); } catch (e) { /* not allowed in some previews */ } }
  }
  function closeDrawer() {
    open = null;
    $("#drawer").hidden = true; $("#drawerBackdrop").hidden = true;
    if (!DEMO) { try { history.replaceState(null, "", location.pathname + location.search); } catch (e) { /* ignore */ } }
  }

  function showTab(name) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $$(".panel").forEach((p) => (p.hidden = p.dataset.panel !== name));
  }

  // ---------- events ----------
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-bill],[data-rso]");
    if (!el || el.closest("#stats")) return;
    if (el.tagName === "A") e.preventDefault();
    if (el.dataset.bill) openDrawer("bill", el.dataset.bill);
    else if (el.dataset.rso) openDrawer("rso", el.dataset.rso);
  });
  $$(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("#drawerClose").addEventListener("click", closeDrawer);
  $("#drawerBackdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  ["#billSearch", "#billQueue", "#billStatus", "#billLevel"].forEach((s) => $(s).addEventListener("input", renderBills));
  ["#rsoSearch", "#rsoLevel"].forEach((s) => $(s).addEventListener("input", renderRsos));
  $("#refreshBtn").addEventListener("click", () => load(true));
  $("#fySelect").addEventListener("change", (e) => { fy = Number(e.target.value); load(); });

  function fromHash() {
    const m = location.hash.match(/^#(bill|rso)=(.+)$/);
    if (!m) return;
    const id = decodeURIComponent(m[2]);
    if (!DATA) { open = { type: m[1], id }; return; }
    if (m[1] === "bill" && !byBill.has(id)) {
      $("#errorBanner").hidden = false;
      $("#errorBanner").textContent = `Bill ${id} isn't in the data yet. The JFC Data Sheet is refreshed twice a week, so new bills can take a few days to show up.`;
      $("#billSearch").value = id; showTab("bills"); renderBills();
      return;
    }
    openDrawer(m[1], id);
  }
  window.addEventListener("hashchange", fromHash);
  load().then(fromHash);
})();
