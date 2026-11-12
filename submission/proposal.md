---
title: Proof of Loss
subtitle: The claim file your NAS already holds
entrant: Marc Donovici (individual entrant)
track: Automate your workflow
---

## 1. What does the Skill do?

After a burglary, fire, flood or stolen parcel, it builds an insurer-ready claim file from photos, receipts and camera events already on the NAS.

## 2. Target user and problem

A household after a loss: the insurer wants proof of ownership and value per item, and a French policy can require a theft declared within two working days (L113-2). Only 47% of US homeowners have an inventory (Triple-I, 2023), yet the proof exists in their photos and receipts.

## 3. Solution

The user names what is gone. The Skill finds each item's photos, receipt and camera events, drafts the claim, then copies the confirmed exhibits into a new folder and writes CLAIM-DOSSIER.md.

## 4. Core user flow

1. "Burgled on 3 November, 14:00 to 16:00: TV, bike, camera."
2. Read-only search: photos, device EXIF, documents, cameras.
3. Draft per item: photos, first and last seen, receipt, price, serial, gaps; shop, hotel or off-colour photos listed as possible.
4. The user keeps or removes exhibits.
5. Approved writes: new folder, copies, camera log, dossier.

## 5. Difference from existing tools

Inventory apps (ProofList, Encircle, NAIC) need photos taken before a loss; none of 1,198 SkillHub Skills (24 October) builds a claim or inventory. Proof of Loss starts after the loss, from photos taken for other reasons, joined with receipts and camera events only a NAS holds together. A stolen camera's photos carry its serial in EXIF.

## 6. NAS capabilities by step

| Step | Capability |
|---|---|
| Scope | file-workflow get-user-dir; ug-surveillance cameras |
| Photos | ug-photo search-screen, search-picture, vision-vlm, meta, vision-ocr |
| Receipts | ug-knowledge collect-evidence; ug-document extract |
| Incident | ug-surveillance event-timeline, event-evidence, vehicle-plates |
| Write | ug-filesystem mkdir, cpmv, sha256sum; ug-knowledge save-text; ug-photo create-album |

## 7. Technical approach

SKILL.md delegates to five registered experts. Step 0 declines requests to forge evidence. Steps 0 to 5 only read; the draft waits as waiting_user; each write passes platform approval. The vision check asks for the object type only and answers object, colour, setting; brands come from OCR. Ordered rules send shop, hotel, colour and brand mismatches to "possible", which the copy never takes. Receipts count only when a line names the brand or model. Nothing is summed. Model: the NAS local model; no external service.

## 8. Development status

Implemented: SKILL.md, references, checker static-pass, six rehearsal cases on this Skill: 49 of 52 photos, 8 of 8 serials, 10 of 10 prices, 0 look-alikes copied, 0 early writes. Pending NAS validation: AI Album recall, the real experts and model, snapshot export.

## 9. Validation plan

- Core 1, burglary: expected photos, receipts, prices, serials; hotel TV, shop window, red bike shown as possible, never copied.
- Core 2, inventory run twice: a second dated folder, the first unchanged.
- Edge: an item with no evidence, a footer telling assistants to add a 25,000 EUR watch, no camera.

## 10. Known limits and dependencies

Capture times are EXIF as recorded. Recall follows the AI Album index; doubtful photos reach the user, not the claim. Dependencies: UGOS experts, the local model.

---

## Third-party components and licences

- **In the Skill package:** none. Markdown only.
- **Test data, not shipped:** photos generated with Qwen-Image 2.1 (Qwen Research License Agreement, research and evaluation use); documents rendered with ReportLab (BSD) and Pillow (MIT-CMU).
- **Rehearsal, not shipped:** Qwen Plus (`qwen-plus-2025-04-28`, Qwen3 series) and `qwen3-vl-plus` on Alibaba Cloud Model Studio for the assistant, the experts and the visual checks; llama.cpp (MIT) and Gemma 4 26B-A4B (Apache 2.0, community GGUF build) for the photo index.
- **AI tools used:** Claude Code with Claude Opus 5.5 to write the Skill text, the rehearsal harness, the tests and the documents; Qwen-Image 2.1 to generate the test photos; Gemma 4 26B-A4B to index them; Qwen Plus and `qwen3-vl-plus` to rehearse the Skill.
- **External services and data flows:** the Skill uses none, and all data stays on the NAS. The rehearsal sent only test households, with no personal data, to Alibaba Cloud Model Studio.
