---
name: calendar
description: "Google Calendar CLI at /sandbox/.config/gogcli/bin/gog. Use when: user asks about calendar events, schedule meetings, check availability, RSVP, focus time, out of office, free/busy, conflicts, working location. Run as: /sandbox/.config/gogcli/bin/gog calendar <subcommand>."
---

# gog calendar -- Google Calendar CLI

Manage Google Calendar: list events, create/update/delete events, check availability, RSVP, focus time, out of office.
All commands output JSON. Binary: `/sandbox/.config/gogcli/bin/gog`.

## When to Use

- "What's on my calendar today?"
- "Schedule a meeting with X on Friday at 2pm"
- "Am I free tomorrow between 2-4pm?"
- "Set focus time Thursday afternoon"
- "Cancel the 3pm meeting"
- "RSVP yes to the team lunch"

## Commands

```bash
# List upcoming events (all calendars)
/sandbox/.config/gogcli/bin/gog calendar events list
/sandbox/.config/gogcli/bin/gog calendar events list --max 5

# List calendars
/sandbox/.config/gogcli/bin/gog calendar calendars

# Search events by keyword
/sandbox/.config/gogcli/bin/gog calendar search "standup"

# Create event with attendees
/sandbox/.config/gogcli/bin/gog calendar create primary \
  --title "Team standup" \
  --start "2026-04-10T09:00:00" \
  --duration 30m \
  --attendees "alice@co.com,bob@co.com"

# Update an event
/sandbox/.config/gogcli/bin/gog calendar update primary <eventId> --title "New title"

# Delete an event
/sandbox/.config/gogcli/bin/gog calendar delete primary <eventId>

# Check availability (free/busy)
/sandbox/.config/gogcli/bin/gog calendar freebusy colleague@company.com

# Find scheduling conflicts
/sandbox/.config/gogcli/bin/gog calendar conflicts

# RSVP to an invitation
/sandbox/.config/gogcli/bin/gog calendar respond primary <eventId> --status accepted

# Create focus time block
/sandbox/.config/gogcli/bin/gog calendar focus-time --from "2026-04-10T14:00:00" --to "2026-04-10T17:00:00"

# Set out of office
/sandbox/.config/gogcli/bin/gog calendar out-of-office --from "2026-04-14" --to "2026-04-18"

# Set working location
/sandbox/.config/gogcli/bin/gog calendar working-location --from "2026-04-10" --to "2026-04-10" --type home
```

## Notes

- All output is JSON by default (GOG_JSON=1 is set).
- `primary` refers to the user's default calendar. Use `gog calendar calendars` to list all calendars and their IDs.
- Calendar create sends invites automatically when `--attendees` is provided.
- Token is managed automatically by the host-side push daemon.
