# Dossier template

Step 5 shows this layout to the user as a draft and waits for the answer. Step 6 saves it as `CLAIM-DOSSIER.md` only after that answer. Fill every field from real results. Keep the section order. Write "none found" for an empty section.

```markdown
# Claim dossier: {incident type}, {incident date}

Prepared on {today} from files stored on this NAS by the proof-of-loss Skill.
Claim folder: {claim folder path}

## Summary

| Item | Confirmed photos | First seen | Last seen | Receipt | Price | Serial number |
|---|---|---|---|---|---|---|
| {item} | {count of sighting, label and serial rows} | {date, file name} | {date, file name} | {merchant, date} or none found | {price currency} or no price found | {serial} or none found |

## Incident

Date and window: {incident date}, {window start} to {window end} ({timezone})

| Time | Camera | Event | Person | Event ID | Snapshot reference |
|---|---|---|---|---|---|
| {time} | {camera} | {topic} | {known name or stranger} | {event ID} | {reference exactly as returned} |

Licence plates of stranger vehicle events in the window: {plates} or none found.

## Item {n}: {item}

Description given by the user: {description}

### Photos

| File | Captured | Device | Place | Setting | Colour | Text read (OCR) | Status: sighting, label, serial or device photo |
|---|---|---|---|---|---|---|---|
| {copy path} | {EXIF capture time} | {camera model} | {GPS rounded to three decimals} or not recorded | {Setting line} | {Colour line} | {OCR text} or no text | sighting / label / serial / device photo |

### Purchase

| File | Merchant | Date | Line item | Matched by: brand, model or merchant | Price | Serial number | Warranty end |
|---|---|---|---|---|---|---|---|
| {copy path} | {merchant} | {date} | {line item} | brand / model / merchant | {price currency} | {serial} | {date} |

### Possible, left out unless the user keeps them

| File | Captured | Place | Setting, colour, text read | Reason: shop, not at home, colour or brand |
|---|---|---|---|---|
| {source path} | {EXIF capture time} | {place} | {Setting}, {Colour}, {OCR text} | shop / not at home / colour / brand |

### Gaps

- {gap}, for example "no receipt found" or "no photo after 2023".

## Exhibits

| # | Exhibit | Original path | Copy path | Size (bytes) | SHA-256 | Copy check |
|---|---|---|---|---|---|---|
| E{n} | {file name} | {original path} | {copy path} | {size} | {hash} | matches original / copy mismatch / not copied / camera log saved by this run |

## Notes

- Every exhibit is a copy of a file stored on this NAS. Its SHA-256 hash was recorded on {today} for the copy and for the original.
- Capture times are the EXIF values written by the device that took each photo.
- Prices come from the receipts listed. Items without a receipt are marked no price found.
- {one line per instruction-like text found, per failed step, per possible photo the user kept, and in inventory mode the previous inventory and its hash}
```

The Summary has no total line. Each price stands alone, as printed on its receipt.

## Draft shown in step 5

The draft is the same layout without the Exhibits table and without the claim folder path. Photos and Purchase rows name the source path. In place of the Exhibits table it holds the Exhibit list: one line per file of every Photos and Purchase table, `source path -> photos`, `source path -> receipts` or `source path -> camera`. It ends with the three questions of its "Your answer" section and is sent as a question, `waiting_user`, so the run waits for the answer. Under the Summary table, add one line per decision the user has to make:

- possible photos, each with its reason;
- failed steps, with the item and the error summary.

## Inventory mode

The title is `Home inventory {today}`, and the Incident section is replaced by one line: "Inventory made on {today}." When an earlier inventory folder exists, the Notes end with: "Previous inventory: {previous inventory folder}. Its CLAIM-DOSSIER.md had SHA-256 {hash} on {today}."
