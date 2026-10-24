# Modes

All three modes run the workflow in `SKILL.md`. This page lists what changes.

## claim

The default. For a burglary, theft, fire, flood or water damage.

- Steps 1 to 7 run in order.
- Step 2 searches content captured before the end of the incident window.
- Step 4 runs when at least one camera is registered.
- Default folder name: `Claim {incident date} {incident type}`.
- Fire and water damage usually leave no camera events of interest. Step 4 still lists the window so the user sees when the damage started on camera, when a camera recorded it.

## inventory

A yearly record of valuables, made before anything happens.

- Input 2 is not asked. `{incident end}` in step 2 is today.
- Input 3 lists the valuables to record. When the user gives categories instead, such as "electronics, bikes, jewellery", run step 2 once per category and ask in step 5 which found objects to keep as items.
- Step 4 is left out.
- Default folder name: `Inventory {year}`.
- The dossier title is `Home inventory {year}` and the Incident section is replaced by one line: "Inventory made on {today}."
- Running inventory mode every year creates a new folder each time. Files are never overwritten, so last year's hashes stay valid.

## parcel

A parcel shown as delivered that never reached the user.

- Input 3 is the parcel: what was ordered, the merchant, the order number and the delivery date shown by the carrier.
- Step 2 is optional. Run it only when the user asks for photos of the product.
- Step 3 searches for the order confirmation and the delivery notification.
- Step 4 uses the delivery day as the window and looks first for Package events, then for Human events at the entrance cameras within 30 minutes after a Package event.
- After the dossier is saved, step 6 adds the carrier claim letter with the document expert. The letter uses only the order facts and the delivery events.
- Default folder name: `Parcel claim {order number}`.
