"""Builds the fictional sample data in sample_data/.

Every RSO, person and bill here is made up. The recap file uses the exact column
headers of the real Microsoft Forms export, so the real export can be dropped
in its place.  Run:  python scripts/make_sample_data.py
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl

OUT = Path(__file__).resolve().parent.parent / "sample_data"
OUT.mkdir(exist_ok=True)

RECAP_HEADERS = [
    "ID", "Start time", "Completion time", "Email", "Name", "Last modified time",
    "Please select your RSO:\xa0\nIf you cannot find yourself please use other and put your club name exactly as it appears on Engage.",
    "Name of Event:\nPlease provide the name of the event exactly as it appears on Engage.",
    "Bill/Budget Number:\xa0\nIf there is one bill/budget related to this event, please submit just that bill/budget number.\nIf there are multiple bills/budgets related to this event, please submit in the ...",
    "Event Date and Location:\nPlease provide the date and location of this event.",
    "Number of Attendees:\nPlease provide both the number of GT and non-GT attendees in the form ___ GT, ___ non-GT. \nFor example, 50 GT, 5 non-GT",
    "Proof of Attendance:\nPlease provide proof of the number of attendees given above.\n",
    "Event Summary and Fund Usage Recap:\nPlease provide a brief summary of your event and what your bill/budget funds were used for.",
]
BILL_HEADERS = ["Bill Number", "Organization", "Bill Name", "Event Date", "Submitted Date", "Status", "Category",
                "Amount Requested", "Amount Approved", "Expected Attendance"]

D = lambda s: datetime.strptime(s, "%Y-%m-%d")

# (bill, rso, name, event_date, status, category, requested, approved, expected)
BILLS = [
    # Robotics Collective: always on time
    ("500101", "Robotics Collective", "Robot Build Kickoff", "2026-08-27", "Approved", "Event", 450, 450, 60),
    ("500102", "Robotics Collective", "Arduino Workshop", "2026-09-17", "Approved", "Event", 300, 280, 40),
    ("500103", "Robotics Collective", "Sumo Bot Showcase", "2026-10-15", "Approved", "Event", 600, 600, 80),
    ("500104", "Robotics Collective", "Competition Travel", "2026-11-20", "Approved", "Travel", 1500, 1200, 8),
    # Ceramics Guild: one late recap (strike 1), now caught up
    ("500201", "Ceramics Guild", "Wheel Throwing Night", "2026-09-03", "Approved", "Event", 350, 350, 30),
    ("500202", "Ceramics Guild", "Glaze & Chill", "2026-10-08", "Approved", "Event", 250, 250, 25),
    # Midnight Chess Society: recap missing (strike 1, on hold)
    ("500301", "Midnight Chess Society", "Blitz Tournament", "2026-09-24", "Approved", "Event", 400, 400, 50),
    ("500302", "Midnight Chess Society", "Simul with a Master", "2026-10-20", "Approved", "Event", 700, 650, 70),
    # Trailblazers Hiking Club: two strikes, 30-day freeze running
    ("500401", "Trailblazers Hiking Club", "Welcome Hike", "2026-08-29", "Approved", "Event", 500, 500, 40),
    ("500402", "Trailblazers Hiking Club", "Camping Gear Night", "2026-09-26", "Approved", "Event", 450, 450, 35),
    ("500403", "Trailblazers Hiking Club", "Stone Mountain Sunrise", "2026-11-01", "Approved", "Event", 300, 300, 30),
    # Campus Film Society: three strikes
    ("500501", "Campus Film Society", "Outdoor Movie Night", "2026-08-28", "Approved", "Event", 1200, 1000, 300),
    ("500502", "Campus Film Society", "Horror Marathon", "2026-09-18", "Approved", "Event", 600, 600, 120),
    ("500503", "Campus Film Society", "Student Shorts Screening", "2026-10-02", "Approved", "Event", 500, 450, 100),
    ("500504", "Campus Film Society", "Oscars Watch Party", "2026-11-05", "Pending", "Event", 900, None, 150),
    # Salsa Night Collective: big ask, small turnout; one recap due soon
    ("500601", "Salsa Night Collective", "Fall Social", "2026-09-12", "Approved", "Event", 2500, 2400, 250),
    ("500602", "Salsa Night Collective", "Beginner Lessons", "2026-11-04", "Approved", "Event", 400, 400, 40),
    # Data Science Guild: sent the form but didn't track attendance
    ("500701", "Data Science Guild", "Kaggle Night", "2026-09-30", "Approved", "Event", 350, 350, 45),
    ("500702", "Data Science Guild", "Industry Panel", "2026-10-21", "Approved", "Event", 800, 750, 90),
    # Sustainable Cooking Club: fine, plus an upcoming event
    ("500801", "Sustainable Cooking Club", "Farmers Market Cook-off", "2026-09-19", "Approved", "Event", 450, 420, 50),
    ("500802", "Sustainable Cooking Club", "Thanksgiving Potluck", "2026-11-19", "Approved", "Event", 600, 600, 80),
    # Jazz Ensemble Club: late recap, but JFC waived it (see strike_adjustments.csv)
    ("500901", "Jazz Ensemble Club", "Fall Concert", "2026-09-25", "Approved", "Event", 900, 900, 150),
    # Pre-Law Circle: filed under a different name variant
    ("501001", "Pre-Law Circle", "Mock Trial Night", "2026-10-07", "Approved", "Event", 300, 300, 40),
    # Quiz Bowl Team: bill denied, so no recap needed
    ("501101", "Quiz Bowl Team", "Regional Tournament Hosting", "2026-10-10", "Denied", "Event", 2000, 0, 120),
    ("501102", "Quiz Bowl Team", "Practice Buzzers", "2026-09-15", "Approved", "Equipment", 250, 250, None),
]

# (bill_text, rso_as_typed, event, completed, location, attendees, proof, summary)
RECAPS = [
    ("500101", "Robotics Collective", "Robot Build Kickoff", "2026-08-30 19:05", "8/27/26, Van Leer C341", "58 GT, 2 non-GT", True, "Kickoff meeting. Funds used for pizza and drinks."),
    ("500102", "Robotics Collective", "Arduino Workshop", "2026-09-20 14:12", "9/17/26, Van Leer C456", "41 GT", True, "Hands-on Arduino workshop. Funds used for starter kits."),
    ("Bill #500103", "Robotics Collective", "Sumo Bot Showcase", "2026-10-22 11:40", "10/15/26, Klaus Atrium", "92 GT, 6 non-GT", True, "Showcase of student-built sumo bots. Funds used for arena materials and snacks."),
    ("500201", "Ceramics Guild", "Wheel Throwing Night", "2026-09-25 21:00", "9/3/26, Student Center Craft Room", "28 GT", True, "Wheel throwing intro. Funds used for clay and kiln fees."),
    ("500202", "Ceramics Guild", "Glaze & Chill", "2026-10-12 18:22", "10/8/26, Student Center Craft Room", "24 GT, 1 non-GT", True, "Glazing night. Funds used for glazes."),
    ("500301", "Midnight Chess Society", "Blitz Tournament", "2026-09-28 10:00", "9/24/26, Skiles 006", "46 GT, 4 non-GT", True, "Swiss blitz tournament. Funds used for prizes and boards."),
    ("500401", "Trailblazers Hiking Club", "Welcome Hike", "2026-10-30 09:15", "8/29/26, Sweetwater Creek", "33 GT", True, "First hike of the year. Funds used for van rental."),
    ("500402", "Trailblazers Hiking Club", "Camping Gear Night", "2026-10-30 09:30", "9/26/26, Exhibition Hall", "30 GT", True, "Gear demo. Funds used for snacks and demo tents."),
    ("500502", "Campus Film Society", "Horror Marathon", "2026-10-25 23:59", "9/18/26, Clough 152", "~60", True, "Movie marathon. Funds used for screening license and popcorn."),
    ("500601", "Salsa Night Collective", "Fall Social", "2026-09-20 16:00", "9/12/26, Exhibition Hall Ballroom", "35 GT, 4 non-GT", True, "Social dance with a live band. Funds used for band fee, venue, and catering."),
    ("500701", "Data Science Guild", "Kaggle Night", "2026-10-05 12:00", "9/30/26, Klaus 1443", "N/A", False, "Attendance was not tracked. Funds used for food."),
    ("500702", "Data Science Guild", "Industry Panel", "2026-10-24 15:30", "10/21/26, Scheller 100", "88 GT, 3 non-GT", True, "Panel with four speakers. Funds used for honoraria and refreshments."),
    ("500801", "Sustainable Cooking Club", "Farmers Market Cook-off", "2026-09-23 17:45", "9/19/26, Tech Green", "47 GT, 0 non-GT", True, "Cook-off with local produce. Funds used for ingredients."),
    ("500901", "Jazz Ensemble Club", "Fall Concert", "2026-10-14 20:10", "9/25/26, Ferst Center", "140 GT, 35 non-GT", True, "Fall concert. Funds used for venue tech fees."),
    ("501001", "Pre Law Circle @ GT", "Mock Trial Night", "2026-10-13 13:00", "10/7/26, Instructional Center 109", "22 GT", True, "Mock trial practice. Funds used for food."),
    ("Budget 499870", "Astronomy Club", "Telescope Night", "2026-10-03 22:00", "10/1/26, Tech Green", "35 GT, 5 non-GT", True, "Stargazing night. Budget funds used for hot chocolate."),
    ("N/A", "Astronomy Club", "General Meeting", "2026-10-20 19:00", "N/A", "N/A", False, "N/A"),
]

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Sheet1"
ws.append(RECAP_HEADERS)
first_names = ["Alex", "Jordan", "Sam", "Taylor", "Riley", "Casey", "Morgan", "Jamie", "Avery", "Quinn"]
for i, (bill, rso, event, done, loc, att, proof, summary) in enumerate(RECAPS, 1):
    end = datetime.strptime(done, "%Y-%m-%d %H:%M")
    who = first_names[i % len(first_names)]
    ws.append([
        i, end - timedelta(minutes=6), end, f"{who.lower()}{i}@example.edu", f"{who} Sample", None, rso, event, bill, loc, att,
        f"https://example.sharepoint.com/proof/{i}.png" if proof else "", summary,
    ])
wb.save(OUT / "recap_responses_sample.xlsx")

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Bills"
ws.append(BILL_HEADERS)
for (num, rso, name, ev, status, cat, req, appr, exp) in BILLS:
    ws.append([num, rso, name, D(ev), D(ev) - timedelta(days=21), status, cat, req, appr, exp])
wb.save(OUT / "bills_sample.xlsx")

with open(OUT / "strike_adjustments.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["RSO", "Bill Number", "Action", "Date", "Reason"])
    w.writerow(["Jazz Ensemble Club", "500901", "waive", "2026-10-15", "Extension granted by JVPF over email (venue invoice delay)"])
    w.writerow(["Campus Film Society", "500503", "add", "2026-10-20", "Proof of attendance found to be from a different event"])

print("Wrote sample data to", OUT)
