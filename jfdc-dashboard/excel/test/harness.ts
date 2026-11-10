const fs = require("fs");
const D = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const res = compute(D["recap"], D["Data Pasting Site"], D["CampusLabs_Budget_Requests"], D["Bill Queue"], new Date(2026, 10, 10));
const counts: { [k: string]: number } = {};
res.bills.forEach((b) => { counts[b.recapStatus] = (counts[b.recapStatus] || 0) + 1; });
console.log("bills", res.bills.size, "rsos", res.rsos.size, JSON.stringify(counts));
const lv = [0, 0, 0, 0]; const struck: string[] = [];
res.rsos.forEach((r) => { lv[r.level]++; if (r.level) struck.push(`${r.name}:${r.strikes.length}:${r.eligible}`); });
console.log(lv, struck.sort().join(" | "));

// Run main() against a fake workbook to make sure the Excel calls are wired right.
const sheets: { [k: string]: (string | number | boolean)[][] } = { "Recap Responses": D["recap"], "Data Pasting Site": D["Data Pasting Site"], "CampusLabs_Budget_Requests": D["CampusLabs_Budget_Requests"], "Bill Queue": D["Bill Queue"] };
const written: { [k: string]: number } = {};
function fakeRange(name: string, r: number, c: number, nr: number, nc: number): any {
  const fmt: any = { getFont: () => ({ setBold() {}, setColor() {} }), getFill: () => ({ setColor() {} }), setColumnWidth() {}, setWrapText() {} };
  return {
    getValues: () => sheets[name].slice(r, r + nr).map((row) => { const x = row.slice(c, c + nc); while (x.length < nc) x.push(""); return x; }),
    setValues: (v: any[][]) => { written[name] = v.length; if (v.some((row) => row.length !== nc) || v.length !== nr) throw new Error("bad shape " + name); },
    setValue() {}, getValue: () => "", setFormula() {},
    getRowCount: () => nr, getColumnCount: () => nc, getRowIndex: () => r, getColumnIndex: () => c,
    getFormat: () => fmt,
    addConditionalFormat: () => ({ getTextComparison: () => ({ setRule() {}, getFormat: () => fmt }) }),
  };
}
const wb: any = {
  getWorksheet: (n: string) => sheets[n] ? {
    delete() { delete sheets[n]; },
    getUsedRange: () => fakeRange(n, 0, 0, sheets[n].length, Math.max(...sheets[n].map((x) => x.length))),
    getRangeByIndexes: (a: number, b: number, c: number, d: number) => fakeRange(n, a, b, c, d),
    getRange: (a: string) => fakeRange(n, 0, 0, 1, a.indexOf(":") > 0 && /\d/.test(a) ? 2 : 1), getFreezePanes: () => ({ freezeRows() {} }), getAutoFilter: () => ({ apply() {} }), activate() {},
  } : undefined,
  addWorksheet: (n: string) => { sheets[n] = [[""]]; return wb.getWorksheet(n); },
};
main(wb);
console.log("written", JSON.stringify(written));
