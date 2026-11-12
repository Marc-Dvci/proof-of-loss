# Modes

All three modes run the workflow in `SKILL.md`. This page lists what changes. In every mode the step 5 draft is shown and answered before anything is written.

## claim

The default. For a burglary, theft, fire, flood or water damage.

- Steps 0 to 7 run in order.
- Step 2 searches content captured before the end of the incident window.
- Step 4 runs when at least one camera is registered, and step 6 saves its events as `camera/EVENTS.md`.
- Default folder name: `Claim-{incident date}`.
- Fire and water damage usually leave no camera events of interest. Step 4 still lists the window, so the user sees when a camera recorded the damage starting.

## inventory

A yearly record of valuables, made before anything happens.

- The request is complete when it names at least one valuable: start at step 0 and ask nothing. Input 2 is not asked. `{incident end}` in step 2 is now.
- Input 3 lists the valuables to record. When the user gives categories instead, such as "electronics, bikes, jewellery", run step 2 once per category and ask in step 5 which found objects to keep as items.
- Steps 0, 1, 2, 3, 5, 6 and 7 run. Step 4 is left out.
- Step 5 runs as in the other modes: the draft is shown, and nothing is written before the user answers it.
- Default folder name: `Inventory-{today}`, for example `Inventory-2026-11-04`. A second inventory on the same day gets `Inventory-2026-11-04-2`.
- The dossier title is `Home inventory {today}` and the Incident section is replaced by one line: "Inventory made on {today}."
- **Previous inventory.** Step 1's folder list shows the earlier `Inventory-…` folders. The one that sorts last is the previous inventory. Step 6 hashes its `CLAIM-DOSSIER.md` and the new dossier records that hash in its Notes. Each inventory therefore fixes the one before it, and an insurer can check the whole series.
- Earlier inventory folders are never written into, so their copies and hashes stay valid.

## parcel

A parcel shown as delivered that never reached the user.

- Input 3 is the parcel: what was ordered, the merchant, the order number and the delivery date shown by the carrier.
- Step 2 is optional. Run it only when the user asks for photos of the product.
- Step 3 searches for the order confirmation and the delivery notification.
- Step 4 uses the delivery day as the window and looks first for Package events, then for Human events at the entrance cameras within 30 minutes after a Package event.
- After the dossier is saved, step 6 adds the carrier claim letter with the document expert. The letter uses only the order facts and the delivery events.
- Default folder name: `Parcel-claim-{order number}`.
