---
name: calendar
description: "Google Calendar CLI. NEVER use 'events list' — always use 'events'. Run as: gog calendar events [flags]. Binary: /sandbox/.config/gogcli/bin/gog"
---

# gog calendar — Google Calendar CLI

Binary: `/sandbox/.config/gogcli/bin/gog`

**CRITICAL: The command is `gog calendar events`, NEVER `gog calendar events list`.
Using `events list` causes 404 errors. Always omit `list`.**

## Events — Query

```bash
# Upcoming events (primary calendar)
gog calendar events
gog calendar events --max 5

# Today / tomorrow / this week
gog calendar events --today
gog calendar events --tomorrow
gog calendar events --week

# Next N days
gog calendar events --days 7

# Date range
gog calendar events --from "2026-04-15" --to "2026-04-20"

# Specific calendar by ID (use --cal flag)
gog calendar events --cal="<calendar-id>"
gog calendar events --cal="<calendar-id>" --tomorrow
gog calendar events --cal="<calendar-id>" --max 10

# Specific calendar by passing ID as first argument
gog calendar events "<calendar-id>" --tomorrow

# All calendars at once
gog calendar events --all --today

# List available calendars and their IDs
gog calendar calendars

# Search events by keyword
gog calendar search "standup"
```

## Events — Create / Update / Delete

```bash
# Create event
gog calendar create primary \
  --title "Team standup" \
  --start "2026-04-10T09:00:00" \
  --duration 30m \
  --attendees "alice@co.com,bob@co.com"

# Update an event
gog calendar update primary <eventId> --title "New title"

# Delete an event
gog calendar delete primary <eventId>

# RSVP to an invitation
gog calendar respond primary <eventId> --status accepted
```

## Other Commands

```bash
# Check availability (free/busy)
gog calendar freebusy colleague@company.com

# Find scheduling conflicts
gog calendar conflicts

# Create focus time block
gog calendar focus-time --from "2026-04-10T14:00:00" --to "2026-04-10T17:00:00"

# Set out of office
gog calendar out-of-office --from "2026-04-14" --to "2026-04-18"

# Set working location
gog calendar working-location --from "2026-04-10" --to "2026-04-10" --type home
```

## Notes

- All output is JSON by default (GOG_JSON=1 is set).
- `primary` refers to the user's default calendar. Use `gog calendar calendars` to find other calendar IDs.
- To query a non-primary calendar, use `--cal="<id>"` or pass the ID as the first argument.
- Token is managed automatically by the host-side push daemon.
