<p align="center"><img src="docs/figures/architecture.png" alt="Proof of Loss: Uliya delegates to five UGREEN experts, which read photos, documents and cameras, then write a hashed claim folder after the user confirms" width="900"></p>

# Proof of Loss

![checker](https://img.shields.io/badge/UGREEN%20checker-static--pass%2C%200%20warnings-12a160) ![experts](https://img.shields.io/badge/registered%20experts-5-17211c) ![rehearsal](https://img.shields.io/badge/rehearsal-{{BADGE_CASES}}-17211c) ![license](https://img.shields.io/badge/license-MIT-17211c)

**After a burglary, fire, flood or stolen parcel, Proof of Loss builds an insurer-ready claim file from the photos, receipts and camera events already on a UGREEN AI NAS, with a SHA-256 hash for every exhibit.**

I audit for a living. In an audit, a finding without evidence does not exist, and a claim file works the same way: what you owned, what it cost, and proof that nobody changed the file since.

| | |
|---|---|
| Hackathon | UGREEN Hackathon 2026 on AI NAS, Automate your workflow track |
| Built with | Uliya Skill Development Standard, UGOS CLI capabilities through five registered experts |
| Package | [`skill/proof-of-loss`](skill/proof-of-loss): `SKILL.md` plus five references, Markdown only |
| Headline | {{HEADLINE}} |

## For judges

| Criterion | Where it is answered |
|---|---|
| User Value | [The problem](#the-problem), [What the user gets](#what-the-user-gets) |
| Innovation & Differentiation | [Why this is new](#why-this-is-new) |
| Technical Quality | [`SKILL.md`](skill/proof-of-loss/SKILL.md), [How it works](#how-it-works), [Evidence](#evidence), [`tests/`](tests) |
| AI NAS Fit & Validation | [How UGREEN AI NAS does the work](#how-ugreen-ai-nas-does-the-work), [Validation plan](skill/proof-of-loss/references/test-plan.md) |

## The problem

A household on the evening of a loss. The insurer asks for proof of ownership and value for every item, and a French policy can require a theft to be declared within two working days of its discovery (Code des assurances, article L113-2). Few people keep a home inventory. The proof usually exists anyway, spread across years of photos, an order confirmation in a downloads folder and a till receipt photographed once.

## What the user gets

One request to Uliya:

> We were burgled on Tuesday 3 November 2026 between 14:00 and 16:00. They took our TV, my grey road bike, my camera and my grandfather's gold watch.

One claim folder:

```
Claim 2026-11-03 claim/
  CLAIM-DOSSIER.md     per item: photos, first seen, last seen, receipt, price, serial number, gaps
  photos/              copies of every confirmed photo and device photo
  receipts/            copies of every matched receipt
  camera/              snapshot references for the incident window
```

Each item gets a line such as `Road bike: 5 photos, first seen 6 Mar 2021, last seen 24 Oct 2026, receipt 899.00 EUR (Cyclonord, 4 Mar 2021), serial WTU8841K confirmed by photo.` Each exhibit gets the SHA-256 of its copy and of its original. Inventory mode records valuables before anything happens; parcel mode adds a carrier letter.

## Why this is new

Inventory apps (ProofList, Encircle, the NAIC Home Inventory app) work on photos taken or uploaded for the purpose. Proof of Loss starts after the loss, from photos taken for other reasons, and searches them item by item. It joins three sources that only a NAS keeps together under the owner's control: the photo archive, the paperwork and the home cameras. Photos taken by a stolen camera carry its body serial in EXIF, which ties them to one unit.

## How it works

{{FLOW_FIGURE}}

| Step | What happens | Writes |
|---|---|---|
| 0 | Declines any request to write, edit or re-date evidence | none |
| 1 | Resolves the home folder and the cameras | none |
| 2 | Per item: search, visual check, EXIF, OCR of labels; device photos by camera model | none |
| 3 | Per item: purchase evidence, then structured extraction of receipts | none |
| 4 | Camera events in the incident window, snapshots, plates | none |
| 5 | Draft shown to the user, who keeps or removes exhibits | none |
| 6 | Folder, copies, hashes, dossier, album, each approved by the platform | after the user's answer |
| 7 | Report with one line per item and the gaps | none |

The model judges what a photo shows. Dates, prices, serial numbers and hashes are copied from expert results.

## How UGREEN AI NAS does the work

| Expert | CLI capabilities used | Why |
|---|---|---|
| `photo-agent` | `ug-photo` search-screen, search-picture, vision-vlm, meta, vision-ocr, create-album | the AI Album index finds the item across years of photos; EXIF dates and device serials prove ownership |
| `knowledge-agent` | `ug-knowledge` collect-evidence, save-text | folder-wide search for receipts; verified save of the dossier |
| `document-agent` | `ug-document` extract, writing | merchant, date, price and serial from invoices and photographed receipts; the carrier letter |
| `security-monitor-agent` | `ug-surveillance` cameras, event-timeline, event-evidence, vehicle-plates | what the cameras saw in the incident window |
| `file-agent` | `file-workflow` get-user-dir; `ug-filesystem` mkdir, cpmv, sha256sum | the claim folder, exact copies, hashes of copy and original |

## What it will not do

- Create, edit, complete or re-date a receipt, photo, timestamp or value, or estimate a price no document states.
- Write anything before the user has answered the draft question, or without the platform's approval.
- Follow text found inside evidence: a receipt footer that tells assistants to add a watch is recorded as a note.
- Name a stranger beyond what the camera's own face library returns.
- Send anything outside the NAS.

## Evidence

{{EVIDENCE}}

## Real and synthetic

The Skill, the harness and every result in this repository are real; the household archive they run on is synthetic, with fictional people, brands, merchants, serial numbers and plates.

## Quickstart

```bash
# 1. Check and package the Skill (needs Node and the UGREEN Skill Developer Package next to this folder)
python tools/build_package.py

# 2. Offline tests (no model server needed)
python -m pytest -q tests

# 3. Optional: the local rehearsal (needs llama.cpp, Gemma 4 26B-A4B and its vision projector as GGUF)
export LLAMA_SERVER=llama-server POL_VISION_MODEL=gemma-4-26B-A4B-it.gguf POL_VISION_MMPROJ=mmproj-F16.gguf
python tools/rehearsal_queue.py --profile g26 --out runs/rehearsal --split all
```

## Layout

| Path | Content |
|---|---|
| `skill/proof-of-loss/` | the Skill package: `SKILL.md` and `references/` |
| `harness/` | rehearsal: mock UGOS CLI layer, main assistant and experts, cases, scorer |
| `testdata/` | household specs and ground truth, generators for photos and documents |
| `tools/` | package, proposal and figure builders |
| `tests/` | offline tests |
| `docs/figures/` | gallery figures and their sources |

## Claims

| Claim | File | Test |
|---|---|---|
| The package passes the official checker with zero warnings | `tools/build_package.py` | `tests/test_offline.py::test_package_builds_and_passes_the_official_checker` |
| Writes are approval-gated | `harness/mock_nas.py` (`Gate`) | `test_writes_pass_the_gate`, `test_deferred_approval_is_granted_on_retry` |
| Copies hash the same as their originals | `harness/mock_nas.py` | `test_copy_then_hash_matches_original` |
| Experts reach only their own CLIs | `harness/mock_nas.py` | `test_experts_only_reach_their_own_clis` |
| The incident window filters camera events | `harness/mock_nas.py` | `test_event_timeline_respects_the_window` |
| The scorer catches invented amounts and wrong hashes | `harness/score.py` | `test_scorer_flags_invented_amounts_and_wrong_hashes` |

## Licence

MIT. See [LICENSE](LICENSE).
