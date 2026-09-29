// CampusLabs budget-request scraper — revised
// Run from the DevTools console on the CampusLabs budgeting "reviews" list page.
// See campuslabs_scraper_review.md for what changed and why.

(async () => {
    // ============================================================
    // SETTINGS
    // ============================================================

    const DETAIL_BASE =
        "https://gatech.campuslabs.com/engage/budgeting/reviews#/edit/";
    const TAB_INFO = "?selectedTab=additionalInformation";
    const TAB_BUDGET = "?selectedTab=budget";

    const POLL_MS = 500;            // how often to check the page
    const PAGE_TIMEOUT_MS = 20000;  // give up on a page after this long
    const STABLE_POLLS = 2;         // page text must stop changing for this many polls

    // ============================================================
    // HELPERS
    // ============================================================

    const sleep = ms => new Promise(r => setTimeout(r, ms));

    function csvEscape(value) {
        let s = value == null
            ? ""
            : String(value).replace(/\r?\n/g, " ").trim();

        // Stop Excel/Sheets from executing student-entered text as a formula
        if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;

        return '"' + s.replace(/"/g, '""') + '"';
    }

    function toLines(text) {
        return text
            .split(/\r?\n/)
            .map(l => l.trim())
            .filter(l => l.length > 0);
    }

    // ============================================================
    // 1. BILL NUMBERS FROM CURRENT PAGE
    // ============================================================

    const billNumbers = [...new Set(
        [...document.body.innerText.matchAll(/No\.\s*(\d{6})(?!\d)/gi)]
            .map(m => m[1])
    )];

    console.log(`Found ${billNumbers.length} bill numbers:`, billNumbers);
    console.log("Note: only bills visible on this page are included. " +
        "If the list is paginated, show all rows first.");

    if (billNumbers.length === 0) {
        console.error("No bill numbers were found.");
        return;
    }

    // ============================================================
    // 2. DETAIL WINDOW
    // ============================================================

    const detailWindow = window.open("about:blank", "CampusLabsScraperWindow");

    if (!detailWindow) {
        console.error("Pop-up blocked. Allow pop-ups for CampusLabs and run again.");
        return;
    }

    // ============================================================
    // 3. LOAD A PAGE AND WAIT UNTIL IT IS REALLY READY
    // ============================================================
    // The detail URLs are hash routes, so changing the URL does NOT
    // reload the page — the old bill's text stays on screen until the
    // app re-renders. So we wait until the text:
    //   (a) differs from the previous page we scraped,
    //   (b) contains the markers for this tab, and
    //   (c) has stopped changing.
    // ============================================================

    let lastText = "";

    const isInfoReady = t =>
        /request history/i.test(t) && /^\s*2\.\s/m.test(t);

    const isBudgetReady = t =>
        /requested total/i.test(t);

    function readWindowText() {
        try {
            return detailWindow.document?.body?.innerText || "";
        } catch {
            return "";
        }
    }

    async function loadPage(url, isReady) {
        const previous = lastText;
        detailWindow.location.href = url;

        const deadline = Date.now() + PAGE_TIMEOUT_MS;
        let candidate = null;
        let stable = 0;

        while (Date.now() < deadline) {
            await sleep(POLL_MS);
            if (detailWindow.closed) throw new Error("Detail window was closed");

            const text = readWindowText();

            if (text && text !== previous && isReady(text)) {
                if (text === candidate) {
                    if (++stable >= STABLE_POLLS) {
                        lastText = text;
                        return { text, ready: true };
                    }
                } else {
                    candidate = text;
                    stable = 0;
                }
            } else {
                candidate = null;
                stable = 0;
            }
        }

        const text = readWindowText();
        lastText = text;
        return { text, ready: false };
    }

    // ============================================================
    // 4. PARSERS
    // ============================================================

    // Split the Additional Information page into the question area
    // and the Request History area, so history text never leaks into
    // the last question's answer.
    function splitSections(text) {
        const lines = toLines(text);
        const h = lines.findIndex(l => l.toLowerCase() === "request history");
        return {
            body: h === -1 ? lines : lines.slice(0, h),
            history: h === -1 ? [] : lines.slice(h + 1)
        };
    }

    // Collect the raw lines under each numbered question.
    // A line counts as a new question only if its number comes after
    // the previous question (within a small gap for hidden questions),
    // so numbered lists or dates inside answers aren't mistaken for
    // questions.
    function parseQuestionBlocks(lines) {
        const blocks = {};
        let last = 0;
        let current = null;

        for (const line of lines) {
            const m = line.match(/^(\d{1,3})\.\s*(.*)$/);
            const n = m ? Number(m[1]) : NaN;

            if (m && n > last && n <= last + 3) {
                current = [];
                blocks[n] = current;
                last = n;
                if (m[2]) current.push(m[2].trim());
            } else if (current) {
                current.push(line);
            }
        }
        return blocks;
    }

    function parseBudgetTotals(text) {
        const lines = toLines(text);

        function find(label) {
            for (let i = 0; i < lines.length; i++) {
                const lower = lines[i].toLowerCase();
                if (!lower.startsWith(label)) continue;

                const rest = lines[i].slice(label.length);
                const m = rest.match(/^\s*:?\s*(\(?-?\$?\s?[\d,]+(?:\.\d{1,2})?\)?)/);
                if (m) return m[1].trim();
                return lines[i + 1] || "";
            }
            return "";
        }

        return {
            requestedTotal: find("requested total"),
            reviewerAdjustedTotal: find("reviewer adjusted total")
        };
    }

    // ============================================================
    // 5. SCRAPE EVERY BILL (raw data first)
    // ============================================================

    const raw = [];
    window.scrapedRaw = raw; // partial results survive if something breaks

    for (let i = 0; i < billNumbers.length; i++) {
        const bill = billNumbers[i];
        console.log(`\nProcessing ${i + 1}/${billNumbers.length}: ${bill}`);

        const rec = {
            bill,
            blocks: {},
            history: "",
            requestedTotal: "",
            reviewerAdjustedTotal: "",
            warnings: [],
            error: ""
        };
        raw.push(rec);

        try {
            const info = await loadPage(DETAIL_BASE + bill + TAB_INFO, isInfoReady);
            if (!info.ready) {
                rec.warnings.push("Additional Information timed out; may be incomplete or from previous bill");
            }
            const { body, history } = splitSections(info.text);
            rec.blocks = parseQuestionBlocks(body);
            rec.history = history.join(" | ");

            const budget = await loadPage(DETAIL_BASE + bill + TAB_BUDGET, isBudgetReady);
            if (!budget.ready) {
                rec.warnings.push("Budget tab timed out; totals may be missing or from previous bill");
            }
            Object.assign(rec, parseBudgetTotals(budget.text));

            console.log(rec.warnings.length ? `  ⚠ ${rec.warnings.join("; ")}` : "  ✓ done");
        } catch (err) {
            rec.error = err.message;
            console.error(`  ✗ ${bill}:`, err);
            if (detailWindow.closed) {
                console.error("Detail window closed — stopping early.");
                break;
            }
        }
    }

    try { detailWindow.close(); } catch {}

    // ============================================================
    // 6. SEPARATE QUESTION TEXT FROM ANSWERS
    // ============================================================
    // Question text is identical on every bill, so the question is the
    // run of lines ALL bills share at the start of the block; whatever
    // follows is that bill's answer. This keeps multi-line answers
    // intact and handles blank answers. With only one bill, fall back
    // to "last line = answer".
    // ============================================================

    const maxQ = Math.max(0, ...raw.flatMap(r => Object.keys(r.blocks).map(Number)));
    const qText = {};
    const qPrefix = {};

    for (let n = 1; n <= maxQ; n++) {
        const blocks = raw.map(r => r.blocks[n]).filter(Boolean);

        if (blocks.length === 0) {
            qText[n] = `Question ${n}`;
            qPrefix[n] = 0;
            continue;
        }

        const maxLen = Math.max(...blocks.map(b => b.length));
        let p = 0;

        if (blocks.length > 1) {
            while (
                p < maxLen &&
                blocks.every(b => b[p] !== undefined && b[p] === blocks[0][p])
            ) p++;
        } else {
            p = maxLen - 1;
        }

        // Always leave room for an answer line on the longest block
        p = Math.max(0, Math.min(p, maxLen - 1));

        qPrefix[n] = p;
        const longest = blocks.reduce((a, b) => (b.length > a.length ? b : a));
        qText[n] = longest.slice(0, p).join(" ") || `Question ${n}`;
    }

    // ============================================================
    // 7. BUILD ROWS + CSV
    // ============================================================

    const questionHeaders = [];
    for (let n = 1; n <= maxQ; n++) questionHeaders.push(`Q${n}: ${qText[n]}`);

    const headers = [
        "Bill Number",
        ...questionHeaders,
        "Requested Total",
        "Reviewer Adjusted Total",
        "Request History",
        "Warnings",
        "Error"
    ];

    const results = raw.map(r => {
        const row = { "Bill Number": r.bill };
        for (let n = 1; n <= maxQ; n++) {
            const block = r.blocks[n] || [];
            row[questionHeaders[n - 1]] = block
                .slice(qPrefix[n])
                .join(" ")
                .replace(/^-\s*/, "")
                .trim();
        }
        row["Requested Total"] = r.requestedTotal;
        row["Reviewer Adjusted Total"] = r.reviewerAdjustedTotal;
        row["Request History"] = r.history;
        row["Warnings"] = r.warnings.join("; ");
        row["Error"] = r.error;
        return row;
    });

    const csv = [
        headers.map(csvEscape).join(","),
        ...results.map(row => headers.map(h => csvEscape(row[h])).join(","))
    ].join("\r\n");

    // BOM so Excel reads UTF-8 (curly quotes, accents, emoji) correctly
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `CampusLabs_Budget_Requests_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);

    window.scrapedResults = results;

    const flagged = results.filter(r => r.Warnings || r.Error).length;
    console.log("\n========================================");
    console.log(`DONE — ${results.length} bills, ${maxQ} questions.`);
    if (flagged) console.warn(`${flagged} bill(s) have warnings/errors — check those columns.`);
    console.log("========================================");
})();