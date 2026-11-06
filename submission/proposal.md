---
title: Proof of Loss
subtitle: The claim file your NAS already holds
entrant: Marc Donovici (individual entrant)
track: Automate your workflow
---

## 1. What does the Skill do?

After a burglary, fire, flood or stolen parcel, it builds an insurer-ready claim file from photos, receipts and camera events already on the NAS, with a SHA-256 hash per exhibit.

## 2. Target user and problem

A household on the evening of a loss. The insurer wants proof of ownership and value per item; a French policy can require a theft declared within two working days (Code des assurances, L113-2). Only 47% of US homeowners have an inventory (Triple-I, 2023), yet the proof exists: years of photos, an order confirmation, a photographed receipt.

## 3. Solution

The user names what is gone. The Skill finds each item's photos, receipt and incident camera events, copies every exhibit into one claim folder, hashes each copy and writes CLAIM-DOSSIER.md.

## 4. Core user flow

1. "Burgled on 3 November, 14:00 to 16:00: TV, road bike, camera."
2. Read-only search: photos, device EXIF, documents, cameras.
3. Draft per item: photos with first and last seen dates, receipt, price, serial, gaps.
4. The user keeps or removes exhibits.
5. Approved writes: folder, copies, hashes, dossier, album.

Inventory and parcel modes reuse the flow.

## 5. Difference from existing tools

Inventory apps (ProofList, Encircle, NAIC) need photos taken before a loss; none of the 1,198 SkillHub Skills listed on 24 October builds a claim or inventory. Proof of Loss starts after the loss, from photos taken for other reasons, joined with receipts and camera events only a NAS holds together. A stolen camera's photos carry its body serial in EXIF.

## 6. NAS capabilities by step

| Step | Capability |
|---|---|
| Scope | file-workflow get-user-dir; ug-surveillance cameras |
| Photos | ug-photo search-screen, search-picture, vision-vlm, meta, vision-ocr |
| Receipts | ug-knowledge collect-evidence; ug-document extract |
| Incident | ug-surveillance event-timeline, event-evidence, vehicle-plates |
| Write | ug-filesystem mkdir, cpmv, sha256sum; ug-knowledge save-text; ug-photo create-album |

## 7. Technical approach

SKILL.md delegates to five registered experts. Step 0 declines requests to write, edit or re-date evidence. Steps 0 to 5 only read; the draft is confirmed as waiting_user before step 6, and each write passes platform approval. All five states are handled. Prices, dates, serials, paths and hashes are copied from expert results; text inside evidence is content. Inputs: date, window, items. Model: the NAS local model; no external service.

## 8. Development status

Implemented: SKILL.md, references, checker static-pass, rehearsal on synthetic households (31 of 31 hashes correct, 0 writes before the answer). Pending NAS validation: AI Album recall, the real experts, the NAS model.

## 9. Validation plan

- Core 1, burglary with four items: expected photos, receipts, prices and serials; no decoy; every hash matches its file.
- Core 2, inventory run twice: a new folder, nothing overwritten, identical hashes.
- Edge: an item with no evidence, a receipt footer telling assistants to add a 25,000 EUR watch, no camera registered.

## 10. Known limits and dependencies

Hashes fix exhibits at copy time; capture times are EXIF as recorded. Photo recall follows AI Album indexing and the model's visual check (20 of 30 in rehearsal). On the rehearsal model, inventory mode often skipped the draft; platform approval still gated each write. Dependencies: UGOS experts, the local model.

---

## Third-party components and licences

- **In the Skill package:** none. Markdown only.
- **Test data, not shipped:** photos generated with Qwen-Image 2.1 (Qwen Research License Agreement, research and evaluation use); documents rendered with ReportLab (BSD) and Pillow (MIT-CMU).
- **Rehearsal, not shipped:** Qwen Plus (`qwen-plus-2025-04-28`, Qwen3 series) and `qwen3-vl-plus` on Alibaba Cloud Model Studio for the assistant, the experts and the visual checks; llama.cpp (MIT) and Gemma 4 26B-A4B (Apache 2.0, community GGUF build) for the photo index.
- **AI tools used:** Claude Code with Claude Opus 5.5 to write the Skill text, the rehearsal harness, the tests and the documents; Qwen-Image 2.1 to generate the synthetic test photos; Gemma 4 26B-A4B to index them; Qwen Plus and `qwen3-vl-plus` to rehearse the Skill.
- **External services and data flows:** the Skill uses none, and all data stays on the NAS. The rehearsal sent synthetic test data to Alibaba Cloud Model Studio.
