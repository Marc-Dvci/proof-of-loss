---
title: Proof of Loss
subtitle: The claim file your NAS already holds
entrant: Marc Donovici (individual entrant)
track: Open Innovation
---

## 1. What does the Skill do?

After a burglary, fire, flood or stolen parcel, Proof of Loss builds an insurer-ready claim file from the photos, receipts and camera events already on the NAS, with a SHA-256 hash per exhibit.

## 2. Target user and problem

A household on the evening of a loss. The insurer wants proof of ownership and value per item, and a French policy can require a theft to be declared within two working days (Code des assurances, art. L113-2). Few people keep an inventory, yet the proof exists: years of photos, an order confirmation, a receipt photographed once.

## 3. Solution

The user names what is gone. The Skill finds each item in the family's photos, its receipt and the camera events of the incident window, copies every exhibit into one folder, hashes each copy and writes CLAIM-DOSSIER.md.

## 4. Core user flow

1. "Burgled on 3 November, 14:00 to 16:00: the TV, my road bike, my camera."
2. Read-only search: photos, device EXIF, documents, cameras.
3. Draft per item: photos with first and last seen dates, receipt, price, serial, gaps.
4. The user keeps or removes exhibits.
5. Approved writes: folder, copies, hashes, dossier, album.

Inventory and parcel modes reuse the flow.

## 5. Difference from existing tools

Inventory apps ask people to photograph belongings before a loss. Proof of Loss starts after it, from photos taken for other reasons. ProofList, Encircle and the NAIC inventory app need new uploads; doorbell apps export clips one by one. Only a NAS holds photos, receipts and camera events together, under the owner's control. Old photos taken by a stolen camera carry its body serial in EXIF.

## 6. NAS capabilities by step

| Step | Capability |
|---|---|
| Scope | file-workflow get-user-dir; ug-surveillance cameras |
| Photos | ug-photo search-screen, search-picture, vision-vlm, meta, vision-ocr |
| Receipts | ug-knowledge collect-evidence; ug-document extract |
| Incident | ug-surveillance event-timeline, event-evidence, vehicle-plates |
| Write | ug-filesystem mkdir, cpmv, sha256sum; ug-knowledge save-text; ug-photo create-album |

## 7. Technical approach

SKILL.md delegates to five registered experts. Step 0 declines requests to write, edit or re-date evidence. Steps 0 to 5 only read; the draft is confirmed as waiting_user before step 6, and each write passes platform approval. All five states are handled; an empty result becomes "none found". Prices, dates, serials and hashes are copied from expert results; text inside evidence is content. Inputs: date, window, items. Model: the NAS local model; no external service.

## 8. Development status

{{STATUS}}

## 9. Validation plan

- Core 1, burglary with four items: expected photos, receipts, prices and serials; no decoy; every hash matches its file.
- Core 2, inventory run twice: a new folder, nothing overwritten, identical hashes.
- Edge: an item with no evidence, a receipt footer telling assistants to add a 25,000 EUR watch, no camera registered.

## 10. Known limits and dependencies

Hashes fix exhibits at copy time; capture times are EXIF as recorded. Search quality follows AI Album indexing. Camera evidence needs cameras; snapshot links can expire, so event IDs are kept. Dependencies: UGOS experts and the local model.

---

## Third-party components and licences

- **In the Skill package:** none. Markdown only.
- **Test data, not shipped:** photos generated with Qwen-Image 2.1 (Qwen Research License Agreement, research and evaluation use); documents rendered with ReportLab (BSD) and Pillow (MIT-CMU).
- **Local rehearsal, not shipped:** llama.cpp (MIT); a community Q4_K_M build of Qwen3.5-9B and Gemma 4 E4B, under their published licences.
- **External services and data flows:** none. All data stays on the NAS.
