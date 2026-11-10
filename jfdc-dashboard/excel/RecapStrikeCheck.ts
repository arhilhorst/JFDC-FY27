/**
 * JFC Recap & Strike Check (Office Script for Excel on the web)
 * -------------------------------------------------------------
 * Gives the same answers as the dashboard, inside the JFC Data Sheet.
 *
 * Setup (once): open the JFC Data Sheet in Excel on the web > Automate > New Script,
 * paste this whole file, Save as "Recap Strike Check".
 * Each run: make sure a sheet named "Recap Responses" holds the Post-Event Recap
 * Form export (paste it, or keep it as a linked copy), then click Run.
 *
 * It reads:   "Data Pasting Site" (Engage export), "CampusLabs_Budget_Requests"
 *             (event dates, Q3), "Bill Queue", and "Recap Responses".
 * It writes:  "Recap Check" (one row per bill), "Recap Check RSOs" (one row per RSO),
 *             and "Bill Lookup" (type a bill number, see the RSO's status).
 *
 * Rules: SAF Policy (Sept 2026) §9.5.1-9.5.2. A recap is due 14 days after the
 * event. Late, missing, or attendance-not-tracked = a strike. Strikes reset July 1.
 *   Each strike is numbered (Strike 1, 2, 3) within the fiscal year.
 */

// ---------- settings (match config.json in the dashboard) ----------
const RECAP_SHEET = "Recap Responses";
const ENGAGE_SHEET = "Data Pasting Site";
const ANSWERS_SHEET = "CampusLabs_Budget_Requests";
const QUEUE_SHEET = "Bill Queue";
const DEADLINE_DAYS = 14;
const FREEZE_DAYS = 30;
const POLICY_START = "2026-07-01"; // bills first submitted before this never need a recap
const FUNDED_STATUSES = ["approved", "funded", "partially approved", "paid", "complete", "completed"];
const BILL_PROCESS = /Bills Process/i;

type Cell = string | number | boolean;
interface Recap { rso: string; key: string; submitted: Date | null; bills: string[]; eventText: string; tracked: boolean; event: string; }
interface Bill {
  num: string; rso: string; key: string; title: string; submitted: Date | null; status: string; category: string;
  requested: number; approved: number; eventDate: Date | null; eventSource: string; inQueue: boolean; says: string;
  recapStatus: string; strikeDate: Date | null; recapSubmitted: Date | null; due: Date | null;
}
interface Strike { bill: string; date: Date; resolved: Date | null; reason: string; }
interface Rso { name: string; key: string; strikes: Strike[]; level: number; eligible: boolean; reason: string; counts: Map<string, number>; }

const LABELS: { [k: string]: string } = {
  on_time: "Recap submitted on time", late: "Recap submitted late", missing: "Recap missing (overdue)",
  not_tracked: "Attendance not tracked", pending: "Recap not due yet", upcoming: "Event hasn't happened",
  submitted_no_date: "Recap submitted (event date unknown)", no_date: "No recap yet (event date unknown)",
  not_funded: "Not approved, no recap needed", before_policy: "Before recap rule started", not_required: "No recap required",
};
const LEVELS = ["No strikes", "Strike 1", "Strike 2", "Strike 3"];

// ---------- helpers ----------
function str(v: Cell | undefined): string { return v === undefined || v === null ? "" : String(v).trim(); }
function day(d: Date): Date { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
function addDays(d: Date, n: number): Date { const x = new Date(d.getTime()); x.setDate(x.getDate() + n); return day(x); }
function diffDays(a: Date, b: Date): number { return Math.round((day(a).getTime() - day(b).getTime()) / 86400000); }
function fmt(d: Date | null): string { return d ? `${d.getMonth() + 1}/${d.getDate()}/${d.getFullYear()}` : ""; }
function fromSerial(n: number): Date { const ms = Math.round((n - 25569) * 86400000); const d = new Date(ms); return new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes()); }

function toDate(v: Cell | undefined): Date | null {
  if (typeof v === "number") return v > 20000 && v < 80000 ? fromSerial(v) : null;
  const s = str(v);
  if (!s) return null;
  if (/^\d{5}(\.\d+)?$/.test(s)) return fromSerial(parseFloat(s));
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
  const t = Date.parse(s);
  return isNaN(t) ? null : new Date(t);
}

function normRso(name: string): string {
  let s = name.toLowerCase().replace(/&/g, " and ").replace(/@/g, " at ");
  s = s.replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ");
  s = s.replace(/\b(the|inc|at georgia tech|at gt|georgia tech|gt)\b/g, " ");
  return s.replace(/\s+/g, " ").trim();
}

function billNumbers(v: Cell | undefined): string[] {
  const out: string[] = [];
  const re = /(?<![\d.])(\d{5,6})(?![\d.])/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(str(v))) !== null) if (out.indexOf(m[1]) < 0) out.push(m[1]);
  return out;
}

function cleanNum(v: Cell | undefined): string {
  const m = str(v).match(/\d{4,7}/);
  return m ? m[0] : str(v);
}

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
function eventDateFromText(text: string, submitted: Date | null): Date | null {
  const s = text.toLowerCase().replace(/(\d)(st|nd|rd|th)\b/g, "$1");
  let mo = 0, dy = 0, yr = 0;
  const a = s.match(/(?<![\d.])(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?!\d)/);
  if (a) { mo = +a[1]; dy = +a[2]; yr = a[3] ? +a[3] : 0; }
  else {
    const b = s.match(/(jan|feb|mar|apr|may|jun|jul|aug|sep|set|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?/);
    if (!b) return null;
    mo = MONTHS.indexOf(b[1] === "set" ? "sep" : b[1]) + 1; dy = +b[2]; yr = b[3] ? +b[3] : 0;
  }
  if (yr > 0 && yr < 100) yr += 2000;
  const guessed = yr === 0;
  if (guessed) yr = submitted ? submitted.getFullYear() : new Date().getFullYear();
  if (mo < 1 || mo > 12 || dy < 1 || dy > 31) return null;
  let d = new Date(yr, mo - 1, dy);
  if (guessed && submitted && d.getTime() > addDays(submitted, 1).getTime()) d = new Date(yr - 1, mo - 1, dy);
  if (submitted && Math.abs(diffDays(submitted, d)) > 400) return null;
  return d;
}

function attendanceTracked(text: string): boolean {
  const low = text.toLowerCase().trim();
  if (!low || /^(n\/?a\.?|none|-|0)$/.test(low) || /not tracked|did not track|didn't track/.test(low)) return false;
  if (/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d/.test(low) && !/gt/.test(low)) return false;
  return /\d/.test(low);
}

function fiscalYear(d: Date): number { return d.getMonth() >= 6 ? d.getFullYear() + 1 : d.getFullYear(); }

function readSheet(workbook: ExcelScript.Workbook, name: string): Cell[][] {
  const ws = workbook.getWorksheet(name);
  if (!ws) return [];
  const used = ws.getUsedRange(true);
  if (!used) return [];
  const rows = used.getRowCount(), cols = used.getColumnCount();
  const r0 = used.getRowIndex(), c0 = used.getColumnIndex();
  const out: Cell[][] = [];
  const CHUNK = 5000; // keep each read small enough for Excel on the web
  for (let r = 0; r < rows; r += CHUNK) {
    const n = Math.min(CHUNK, rows - r);
    const vals = ws.getRangeByIndexes(r0 + r, c0, n, cols).getValues() as Cell[][];
    for (const v of vals) out.push(v);
  }
  return out;
}

/** Finds the real header row (some sheets have a "Column1, Column2..." row on top). */
function headerIndex(rows: Cell[][], mustHave: string[]): { at: number; col: (prefix: string) => number } {
  for (let i = 0; i < Math.min(rows.length, 6); i++) {
    const h = rows[i].map((c) => str(c).replace(/ /g, " ").split("\n")[0].toLowerCase());
    if (mustHave.every((m) => h.some((x) => x.startsWith(m)))) {
      return { at: i, col: (p: string) => h.findIndex((x) => x.startsWith(p)) };
    }
  }
  return { at: -1, col: () => -1 };
}

// ---------- the calculation (no Excel calls; shared with the tests) ----------
function compute(recapRows: Cell[][], engageRows: Cell[][], answerRows: Cell[][], queueRows: Cell[][], today: Date) {
  today = day(today);
  const fy = fiscalYear(today);
  const fyStart = new Date(fy - 1, 6, 1), fyEnd = new Date(fy, 5, 30);
  const policyStart = toDate(POLICY_START);

  // Recaps
  const recaps: Recap[] = [];
  const rh = headerIndex(recapRows, ["bill/budget number"]);
  if (rh.at >= 0) {
    const cT = rh.col("completion time"), cR = rh.col("please select your rso"), cB = rh.col("bill/budget number"),
      cD = rh.col("event date and location"), cA = rh.col("number of attendees"), cP = rh.col("proof of attendance"),
      cE = rh.col("name of event");
    for (const r of recapRows.slice(rh.at + 1)) {
      if (!r.some((c) => str(c))) continue;
      const proof = str(r[cP]);
      recaps.push({
        rso: str(r[cR]), key: normRso(str(r[cR])), submitted: toDate(r[cT]), bills: billNumbers(r[cB]),
        eventText: str(r[cD]), event: str(r[cE]),
        tracked: attendanceTracked(str(r[cA])) && !!proof && !/^(n\/?a|none|-)$/i.test(proof),
      });
    }
  }

  // Bill form answers
  const answers = new Map<string, { date: Cell; says: string }>();
  const ah = headerIndex(answerRows, ["bill number"]);
  if (ah.at >= 0) {
    const cN = ah.col("bill number"), c3 = ah.col("q3"), c8 = ah.col("q8");
    for (const r of answerRows.slice(ah.at + 1)) {
      const n = cleanNum(r[cN]);
      if (n) answers.set(n, { date: c8 >= 0 ? r[c8] : "", says: c3 >= 0 ? str(r[c3]) : "" });
    }
  }

  // Queue
  const queue = new Map<string, string>();
  for (const r of queueRows.slice(1)) { const n = cleanNum(r[0]); if (/^\d+$/.test(n)) queue.set(n, str(r[1])); }

  // Engage line items -> bills
  const bills = new Map<string, Bill>();
  const submitterRso = new Map<string, string>();
  const eh = headerIndex(engageRows, ["id", "processname", "submittedonbehalfof"]);
  if (eh.at >= 0) {
    const ci = (k: string) => eh.col(k);
    const cId = ci("id"), cProc = ci("processname"), cTitle = ci("title"), cWho = ci("submittername"), cFirst = ci("firstsubmitted"),
      cOrg = ci("submittedonbehalfof"), cStat = ci("status"), cReq = ci("requestedamount"), cAdj = ci("adjustedamount"), cSec = ci("sectionname");
    for (const r of engageRows.slice(eh.at + 1)) {
      const org = str(r[cOrg]);
      if (str(r[cWho]) && org) submitterRso.set(str(r[cWho]), org);
      const proc = str(r[cProc]);
      if (!BILL_PROCESS.test(proc)) continue;
      const pm = proc.match(/FY\s*(\d{2,4})/);
      if (pm) { let y = +pm[1]; if (y < 100) y += 2000; if (y < fy - 1) continue; }
      const num = cleanNum(r[cId]);
      let b = bills.get(num);
      if (!b) {
        b = { num, rso: org, key: normRso(org), title: str(r[cTitle]), submitted: toDate(r[cFirst]), status: str(r[cStat]),
          category: "", requested: 0, approved: 0, eventDate: null, eventSource: "", inQueue: queue.has(num), says: "",
          recapStatus: "", strikeDate: null, recapSubmitted: null, due: null };
        bills.set(num, b);
      }
      b.requested += Number(r[cReq]) || 0;
      b.approved += Number(r[cAdj]) || 0;
      const sec = str(r[cSec]).charAt(0).toUpperCase();
      if (sec === "A") b.category = "Event";
      else if (!b.category && sec === "C") b.category = "Travel/Competition";
      else if (!b.category && sec === "B") b.category = "Inventory/Operations";
    }
  }
  queue.forEach((who, num) => {
    if (bills.has(num)) return;
    const org = submitterRso.get(who) || "";
    bills.set(num, { num, rso: org, key: normRso(org), title: "Not in the Engage export yet", submitted: null, status: "In review",
      category: "", requested: 0, approved: 0, eventDate: null, eventSource: "", inQueue: true, says: "", recapStatus: "",
      strikeDate: null, recapSubmitted: null, due: null });
  });

  // Statuses
  const byBill = new Map<string, Recap[]>();
  for (const rc of recaps) for (const n of rc.bills) { if (!byBill.has(n)) byBill.set(n, []); byBill.get(n)!.push(rc); }
  bills.forEach((b) => {
    const a = answers.get(b.num);
    if (a) { b.says = a.says; const d = toDate(a.date); if (d) { b.eventDate = d; b.eventSource = "bill form"; } }
    const matched = (byBill.get(b.num) || []).slice().sort((x, y) => (x.submitted ? x.submitted.getTime() : 9e15) - (y.submitted ? y.submitted.getTime() : 9e15));
    for (const rc of matched) if (rc.key !== b.key && b.key) rc.key = b.key; // same bill = same RSO
    const first = matched.length ? matched[0] : null;
    if (!b.eventDate && first) { const d = eventDateFromText(first.eventText, first.submitted); if (d) { b.eventDate = d; b.eventSource = "recap form"; } }
    b.due = b.eventDate ? addDays(b.eventDate, DEADLINE_DAYS) : null;
    b.recapSubmitted = first ? first.submitted : null;
    const funded = FUNDED_STATUSES.indexOf(b.status.toLowerCase()) >= 0;
    if (!funded) b.recapStatus = "not_funded";
    else if (b.category !== "Event") b.recapStatus = "not_required";
    else if (policyStart && b.submitted && b.submitted < policyStart) b.recapStatus = "before_policy";
    else if (first) {
      const sub = first.submitted ? day(first.submitted) : null;
      if (!matched.some((m) => m.tracked)) { b.recapStatus = "not_tracked"; b.strikeDate = sub || today; }
      else if (!b.due) b.recapStatus = "submitted_no_date";
      else if (sub && sub > b.due) { b.recapStatus = "late"; b.strikeDate = addDays(b.due, 1); }
      else b.recapStatus = "on_time";
    } else if (!b.eventDate) b.recapStatus = "no_date";
    else if (b.eventDate > today) b.recapStatus = "upcoming";
    else if (today <= b.due!) b.recapStatus = "pending";
    else { b.recapStatus = "missing"; b.strikeDate = addDays(b.due!, 1); }
  });

  // RSOs
  const rsos = new Map<string, Rso>();
  const getRso = (key: string, name: string) => {
    if (!rsos.has(key)) rsos.set(key, { name, key, strikes: [], level: 0, eligible: true, reason: "", counts: new Map() });
    return rsos.get(key)!;
  };
  bills.forEach((b) => {
    if (!b.key) return;
    const r = getRso(b.key, b.rso);
    r.counts.set(b.recapStatus, (r.counts.get(b.recapStatus) || 0) + 1);
    if (b.strikeDate && b.strikeDate >= fyStart && b.strikeDate <= fyEnd) {
      r.strikes.push({ bill: b.num, date: b.strikeDate, reason: LABELS[b.recapStatus],
        resolved: b.recapStatus === "missing" ? null : (b.recapSubmitted ? day(b.recapSubmitted) : null) });
    }
  });
  for (const rc of recaps) if (rc.key) getRso(rc.key, rc.rso);
  rsos.forEach((r) => {
    r.strikes.sort((x, y) => x.date.getTime() - y.date.getTime());
    r.level = Math.min(r.strikes.length, 3);
    const missing: string[] = [];
    bills.forEach((b) => { if (b.key === r.key && b.recapStatus === "missing" && b.strikeDate && b.strikeDate >= fyStart) missing.push(b.num); });
    r.eligible = true; r.reason = "Eligible for bill review.";
    if (r.level === 3) { r.eligible = false; r.reason = `Third strike: frozen until the fiscal year ends (${fmt(fyEnd)}).`; }
    else if (r.level === 2) {
      const s2 = r.strikes[1];
      if (!s2.resolved) { r.eligible = false; r.reason = `Second strike: frozen until the recap for bill ${s2.bill} is submitted, then 30 more days.`; }
      else { const until = addDays(s2.resolved, FREEZE_DAYS); if (today < until) { r.eligible = false; r.reason = `Second strike: frozen until ${fmt(until)}.`; } }
    }
    if (r.eligible && missing.length) { r.eligible = false; r.reason = `Bills can't be reviewed until overdue recap(s) are submitted: ${missing.join(", ")}.`; }
    if (r.eligible && r.level === 1) r.reason = "First strike recorded (written warning). Recap is in, so bills can be reviewed.";
  });
  return { bills, rsos, recaps, fy };
}

// ---------- Excel output ----------
function writeSheet(workbook: ExcelScript.Workbook, name: string, rows: (string | number)[][], widths: number[]): ExcelScript.Worksheet {
  const old = workbook.getWorksheet(name);
  if (old) old.delete();
  const ws = workbook.addWorksheet(name);
  if (rows.length) {
    const rg = ws.getRangeByIndexes(0, 0, rows.length, rows[0].length);
    rg.setValues(rows);
    const head = ws.getRangeByIndexes(0, 0, 1, rows[0].length);
    head.getFormat().getFont().setBold(true);
    head.getFormat().getFill().setColor("#003057");
    head.getFormat().getFont().setColor("#FFFFFF");
    ws.getFreezePanes().freezeRows(1);
    widths.forEach((w, i) => ws.getRangeByIndexes(0, i, 1, 1).getFormat().setColumnWidth(w));
  }
  return ws;
}

function colorRule(range: ExcelScript.Range, text: string, fill: string, font: string) {
  const cf = range.addConditionalFormat(ExcelScript.ConditionalFormatType.containsText).getTextComparison();
  cf.setRule({ operator: ExcelScript.ConditionalTextOperator.contains, text });
  cf.getFormat().getFill().setColor(fill);
  cf.getFormat().getFont().setColor(font);
}

function colorStrikes(range: ExcelScript.Range) {
  colorRule(range, "Strike 3", "#C62828", "#FFFFFF");
  colorRule(range, "Strike 2", "#FFE0C7", "#9A3412");
  colorRule(range, "Strike 1", "#FFF1B8", "#7A5B00");
  colorRule(range, "No strikes", "#DCF3E2", "#146C2E");
}

function colorRecap(range: ExcelScript.Range) {
  colorRule(range, "missing", "#C62828", "#FFFFFF");
  colorRule(range, "late", "#FFE0C7", "#9A3412");
  colorRule(range, "not tracked", "#FFE0C7", "#9A3412");
  colorRule(range, "event date unknown", "#FFF1B8", "#7A5B00");
  colorRule(range, "on time", "#DCF3E2", "#146C2E");
  colorRule(range, "not due yet", "#DDE9FB", "#1E4F91");
}

function main(workbook: ExcelScript.Workbook) {
  const today = new Date();
  const res = compute(readSheet(workbook, RECAP_SHEET), readSheet(workbook, ENGAGE_SHEET),
    readSheet(workbook, ANSWERS_SHEET), readSheet(workbook, QUEUE_SHEET), today);
  if (!res.recaps.length) console.log(`No recap responses found. Paste the Post-Event Recap Form export into a sheet named "${RECAP_SHEET}".`);

  const billRows: (string | number)[][] = [["Bill #", "RSO", "Bill name", "In review queue", "Engage status", "Type", "Event date",
    "Event date from", "Recap due", "Recap status", "Recap submitted", "RSO strike", "RSO strike count", "Requested", "Approved", "Said all recaps in? (Q3)"]];
  const list: Bill[] = [];
  res.bills.forEach((b) => list.push(b));
  list.sort((x, y) => (Number(y.inQueue) - Number(x.inQueue)) || (Number(y.num) - Number(x.num)));
  for (const b of list) {
    const r = res.rsos.get(b.key);
    billRows.push([/^\d+$/.test(b.num) ? Number(b.num) : b.num, b.rso, b.title, b.inQueue ? "Yes" : "", b.status, b.category, fmt(b.eventDate), b.eventSource, fmt(b.due),
      LABELS[b.recapStatus], fmt(b.recapSubmitted), r ? LEVELS[r.level] : "", r ? r.strikes.length : 0, Math.round(b.requested * 100) / 100, Math.round(b.approved * 100) / 100, b.says]);
  }
  const bs = writeSheet(workbook, "Recap Check", billRows, [70, 220, 240, 70, 90, 110, 80, 80, 80, 210, 90, 90, 90, 80, 80, 90]);
  const n = billRows.length;
  colorRecap(bs.getRangeByIndexes(1, 9, n, 1));
  colorStrikes(bs.getRangeByIndexes(1, 11, n, 1));
  bs.getRangeByIndexes(0, 0, n, billRows[0].length).getFormat().setWrapText(false);
  bs.getAutoFilter().apply(bs.getRangeByIndexes(0, 0, n, billRows[0].length));

  const rsoRows: (string | number)[][] = [["RSO", "Strike count", "Strike", "Strike history",
    "On time", "Late", "Missing", "Attendance not tracked", "Due soon", "No recap yet (date unknown)", "Approved total"]];
  const rl: Rso[] = [];
  res.rsos.forEach((r) => rl.push(r));
  rl.sort((x, y) => (y.level - x.level) || x.name.localeCompare(y.name));
  for (const r of rl) {
    const c = (k: string) => r.counts.get(k) || 0;
    let approved = 0;
    res.bills.forEach((b) => { if (b.key === r.key && b.status.toLowerCase() === "approved") approved += b.approved; });
    rsoRows.push([r.name, r.strikes.length, LEVELS[r.level],
      r.strikes.map((s, i) => `#${i + 1} ${fmt(s.date)} bill ${s.bill} (${s.reason})`).join("; "),
      c("on_time") + c("submitted_no_date"), c("late"), c("missing"), c("not_tracked"), c("pending"), c("no_date"), Math.round(approved * 100) / 100]);
  }
  const rs = writeSheet(workbook, "Recap Check RSOs", rsoRows, [240, 80, 90, 420, 60, 60, 60, 110, 70, 130, 100]);
  colorStrikes(rs.getRangeByIndexes(1, 2, rsoRows.length, 1));
  rs.getAutoFilter().apply(rs.getRangeByIndexes(0, 0, rsoRows.length, rsoRows[0].length));

  // Bill Lookup: type a bill number in B2.
  const old = workbook.getWorksheet("Bill Lookup");
  let lookupValue: string | number = list.length ? list[0].num : "";
  if (old) { lookupValue = old.getRange("B2").getValue() as string | number; old.delete(); }
  const lk = workbook.addWorksheet("Bill Lookup");
  lk.getRange("A1").setValue(`Recap & strike check · SAF Policy §9.5 · run ${fmt(today)} · FY${String(res.fy).slice(2)}`);
  lk.getRange("A1").getFormat().getFont().setBold(true);
  lk.getRange("A2:B2").setValues([["Type a bill number →", lookupValue]]);
  lk.getRange("B2").getFormat().getFill().setColor("#FFF7D6");
  const fields: [string, string][] = [["RSO", "B"], ["Bill name", "C"], ["In review queue", "D"], ["Engage status", "E"],
    ["Event date", "G"], ["Recap due", "I"], ["This bill's recap", "J"], ["Recap submitted", "K"], ["RSO strike", "L"],
    ["RSO strike count", "M"], ["Said all recaps in? (Q3)", "P"]];
  fields.forEach(([label, col], i) => {
    const row = i + 4;
    lk.getRange(`A${row}`).setValue(label);
    lk.getRange(`B${row}`).setFormula(`=IFERROR(INDEX('Recap Check'!$${col}:$${col}, MATCH(--$B$2, 'Recap Check'!$A:$A, 0)), "Bill not found (sheet updates twice a week)")`);
  });
  lk.getRange("A:A").getFormat().setColumnWidth(170);
  lk.getRange("B:B").getFormat().setColumnWidth(520);
  colorStrikes(lk.getRange("B12"));
  colorRecap(lk.getRange("B10"));
  lk.activate();
  console.log(`Done: ${list.length} bills, ${rl.length} RSOs, ${res.recaps.length} recap forms.`);
}
