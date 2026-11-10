"""Strike rules, taken word-for-word from the governing documents.

Source: Joint Policy of the Student Activity Fee & Procedure of the Joint
Finance Committee (SAF Policy, September 2026), Article IX, §9.5.1-9.5.3, p.22.
If the policy changes, update the text and numbers here and in config.json.
"""

POLICY_NAME = "SAF Policy (Sept. 2026)"

CITATIONS = {
    "requirement": {
        "section": "SAF Policy §9.5.1 Post-Event Reporting Requirements",
        "text": (
            "RSOs receiving SAF funding for an event shall be required to track attendance at that event. "
            "Within fourteen calendar days following the event, the sponsoring RSO shall submit a Post-Event "
            "Recap Form containing, at a minimum: 1. Bill or Budget number; 2. Event date and location; "
            "3. Number of attendees; and, 4. Proof of attendance."
        ),
    },
    "noncompliance": {
        "section": "SAF Policy §9.5.2 Noncompliance",
        "text": (
            "Failure to submit a complete Post-Event Recap Form within fourteen calendar days, or failure to "
            "track attendance at an event, shall result in a strike against the RSO."
        ),
    },
    "not_tracked": {
        "section": "SAF Policy §9.5.2 Noncompliance",
        "text": (
            "If an RSO failed to track attendance and is therefore unable to provide proof of attendance, the RSO "
            "must still submit the Post-Event Recap Form with all available required information and indicate "
            "that attendance was not tracked. Submission of the form does not remove the associated strike."
        ),
    },
    "reset": {"section": "SAF Policy §9.5.2 Noncompliance", "text": "Strikes shall reset at the beginning of each Fiscal Year."},
    "fiscal_year": {
        "section": "SAF Policy, Definitions",
        "text": "Fiscal Year: ... from July 1st through June 30th, otherwise referenced as 'FY.'",
    },
    "joint": {
        "section": "SAF Policy §9.5.3 Joint Events and Multiple Funding Sources",
        "text": (
            "If multiple RSOs receive SAF funding for the same event, each RSO that received funding through a "
            "Bill or Budget shall separately submit a Post-Event Recap Form. If an RSO received funding for an "
            "event through multiple Bills or Budgets, all applicable Bill and Budget numbers shall be included on "
            "the Post-Event Recap Form as a comma-separated list."
        ),
    },
    "allowable": {
        "section": "RSO Allowable Cost List, Events",
        "text": (
            "For all events, RSOs must submit a post-event recap that details how the event went, how the funds "
            "were spent, and how many people ended up attending. JFC may use the attendance record of previous "
            "events when applying caps."
        ),
    },
}

# Strike levels. Colors are used by the dashboard badges.
LEVELS = [
    {
        "level": 0,
        "label": "Good standing",
        "short": "No strikes",
        "color": "green",
        "consequence": "No penalties. Bills can be reviewed normally.",
        "section": "SAF Policy §9.5.2",
    },
    {
        "level": 1,
        "label": "Strike 1",
        "short": "Strike 1",
        "color": "yellow",
        "consequence": (
            "The RSO shall receive a written warning and shall be ineligible to have Supplemental Bills reviewed "
            "until the required Post-Event Recap Form is submitted."
        ),
        "section": "SAF Policy §9.5.2(1) First Strike",
    },
    {
        "level": 2,
        "label": "Strike 2",
        "short": "Strike 2",
        "color": "orange",
        "consequence": (
            "The RSO shall be ineligible to have Supplemental Bills reviewed as well as their SGA allocation "
            "account frozen, until the required Post-Event Recap Form is submitted and for thirty calendar days "
            "following its submission."
        ),
        "section": "SAF Policy §9.5.2(2) Second Strike",
    },
    {
        "level": 3,
        "label": "Strike 3",
        "short": "Strike 3",
        "color": "red",
        "consequence": (
            "The RSO shall be ineligible to have Supplemental Bills reviewed as well as their SGA allocation "
            "account frozen, for the remainder of the Fiscal Year. Only outstanding reimbursements may be "
            "processed by SOFO."
        ),
        "section": "SAF Policy §9.5.2(3) Third Strike",
    },
]

# Per-bill recap statuses shown on the dashboard.
RECAP_STATUSES = {
    "on_time": {"label": "Recap submitted on time", "color": "green", "strike": False},
    "late": {"label": "Recap submitted late", "color": "orange", "strike": True},
    "missing": {"label": "Recap missing (overdue)", "color": "red", "strike": True},
    "not_tracked": {"label": "Attendance not tracked", "color": "orange", "strike": True},
    "pending": {"label": "Recap not due yet", "color": "blue", "strike": False},
    "upcoming": {"label": "Event hasn't happened", "color": "gray", "strike": False},
    "submitted_no_date": {"label": "Recap submitted (event date unknown)", "color": "green", "strike": False},
    "no_date": {"label": "No recap yet (event date unknown)", "color": "yellow", "strike": False},
    "not_funded": {"label": "Not approved, no recap needed", "color": "gray", "strike": False},
    "before_policy": {"label": "Before recap rule started", "color": "gray", "strike": False},
    "not_required": {"label": "No recap required", "color": "gray", "strike": False},
    "waived": {"label": "Strike waived by JFC", "color": "gray", "strike": False},
}
