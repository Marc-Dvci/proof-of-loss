# Dossier template

`CLAIM-DOSSIER.md` uses this layout. Fill every field from real results. Keep the section order. Write "none found" for an empty section.

```markdown
# Claim dossier: {incident type}, {incident date}

Prepared on {today} from files stored on this NAS by the proof-of-loss Skill.
Claim folder: {claim folder path}

## Summary

| Item | Confirmed photos | First seen | Last seen | Receipt | Price | Serial number |
|---|---|---|---|---|---|---|
| {item} | {count} | {date, file name} | {date, file name} | {merchant, date} or none found | {price currency} or no price found | {serial} or none found |

Total of listed prices: {total per currency}

## Incident

Date and window: {incident date}, {window start} to {window end} ({timezone})

| Time | Camera | Event | Person | Event ID | Snapshot |
|---|---|---|---|---|---|
| {time} | {camera} | {topic} | {known name or stranger} | {event ID} | {snapshot reference} |

Licence plates on stranger vehicles: {plates} or none found.

## Item {n}: {item}

Description given by the user: {description}

### Photos

| File | Captured | Device | Place | What is visible |
|---|---|---|---|---|
| {file name} | {EXIF capture time} | {camera model} | at home / away {coordinate} / place not recorded | {visual description} |

### Purchase

| File | Merchant | Date | Line item | Price | Serial number | Warranty end |
|---|---|---|---|---|---|---|
| {file name} | {merchant} | {date} | {line item} | {price currency} | {serial} | {date} |

### Gaps

- {gap}, for example "no receipt found" or "no photo after 2023".

## Exhibits

| # | Exhibit | Original path | Copy path | Size (bytes) | SHA-256 of copy | Copy check |
|---|---|---|---|---|---|---|
| E{n} | {file name} | {original path} | {copy path} | {size} | {hash} | matches original / copy mismatch |

## Notes

- Every exhibit is a copy of a file stored on this NAS. Its SHA-256 hash was recorded on {today} for the copy and for the original.
- Capture times are the EXIF values written by the device that took each photo.
- Prices come from the receipts listed. Items without a receipt are marked no price found.
- {one line per instruction-like text found, per failed step, and per possible sighting the user kept}
```

## Draft shown in step 5

The draft is the same layout without the Exhibits hashes and without the claim folder path. Under the Summary table, add one line per decision the user has to make:

- possible sightings, with the detail that contradicts the user description;
- possible receipts;
- failed steps, with the item and the error summary.
