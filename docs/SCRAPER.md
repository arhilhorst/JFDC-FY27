# CampusLabs Budget Request Scraper

A browser-console script that exports every budget request (bill) on the Georgia Tech CampusLabs Engage budgeting **Reviews** page into one CSV. The CSV has one row per bill, with that bill's answers to the Additional Information questions, its budget totals and its request history.

It runs in your own logged-in browser session. There's nothing to install and no credentials are stored.

## Requirements

- A desktop browser with DevTools (Chrome, Edge, Firefox or Safari)
- A CampusLabs account with access to the budgeting reviews at `https://gatech.campuslabs.com/engage/budgeting/reviews`
- Pop-ups allowed for `gatech.campuslabs.com`

## Usage

1. Log in to CampusLabs and open the budgeting **Reviews** list page.
2. **Show every bill you want exported.** The script only picks up bills that are visible on the current page. If the list is paginated, raise the page size or scroll until every row is loaded.
3. Open DevTools (`F12` or `Cmd+Option+I` / `Ctrl+Shift+I`) and switch to the **Console** tab.
4. Paste the full contents of [`campuslabs-scraper.js`](../campuslabs-scraper.js) and press Enter.
   - Chrome may ask you to type `allow pasting` first.
5. A second window opens and steps through each bill. **Leave it open** until the run finishes, because closing it stops the scrape.
6. When it's done, a file named `CampusLabs_Budget_Requests_YYYY-MM-DD.csv` downloads automatically.

The console logs progress (`Processing 3/42: 123456`) and ends with a summary line.

## What it does

1. Finds every 6-digit bill number on the page (text matching `No. 123456`).
2. For each bill, loads two tabs in the detail window:
   - **Additional Information** (`?selectedTab=additionalInformation`) for the numbered questions and the Request History
   - **Budget** (`?selectedTab=budget`) for the Requested Total and Reviewer Adjusted Total
3. Works out the question text by taking the lines that every bill shares at the start of each question. Whatever follows is that bill's answer.
4. Builds the CSV and downloads it.

The detail pages use hash routes, so changing the URL doesn't reload the page. For that reason the script waits until the page text has changed from the previous bill, contains the markers for that tab, and has stopped changing for a moment before it reads anything.

## Output columns

| Column | Contents |
| --- | --- |
| `Bill Number` | 6-digit CampusLabs request number |
| `Organization` | Student organization that submitted the bill, taken from the list row or the detail page. Blank, with a warning, if it can't be found |
| `Q1: …` to `Qn: …` | One column per Additional Information question, with the question text in the header |
| `Requested Total` | Requested total from the Budget tab |
| `Reviewer Adjusted Total` | Reviewer adjusted total from the Budget tab |
| `Request History` | Request History entries, separated by `\|` |
| `Warnings` | Set if a tab timed out, meaning that row's data may be incomplete or belong to the previous bill |
| `Error` | Set if the bill failed outright |

The CSV is UTF-8 with a BOM, so Excel shows accents and curly quotes correctly. Any cell that starts with `=`, `+`, `-` or `@` gets a leading `'` so spreadsheet apps don't run student-entered text as a formula.

**Always check the `Warnings` and `Error` columns before you rely on the data.** If any rows are flagged, re-run the script or check those bills by hand.

## Settings

These are at the top of the script:

| Setting | Default | Purpose |
| --- | --- | --- |
| `POLL_MS` | `500` | How often (in ms) the page is checked |
| `PAGE_TIMEOUT_MS` | `20000` | How long to wait for a tab before giving up and flagging a warning |
| `STABLE_POLLS` | `2` | How many consecutive checks the page text must stay unchanged before it's read |

If you get a lot of timeout warnings on a slow connection, raise `PAGE_TIMEOUT_MS`.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No bill numbers were found.` | You're not on the Reviews list page, or the list hasn't loaded yet. |
| `Pop-up blocked.` | Allow pop-ups for `gatech.campuslabs.com` and run the script again. |
| Fewer bills than expected | The list is paginated. Show all rows before you run the script. |
| `Detail window closed — stopping early.` | The second window was closed during the run. Run the script again. |
| No CSV downloaded | The console keeps partial data in `window.scrapedRaw`, and complete data in `window.scrapedResults` if the run finished. Inspect or copy them from there. |
| Question columns look wrong | Question text is inferred from what all bills have in common. With only one bill, the script can't do that and treats the last line of each block as the answer, so export several bills at once. |

## Data handling

The export contains student organization budget data and free-text answers. Store and share the CSV according to JFDC and Georgia Tech data policies, and don't commit exported CSVs to this repository.
