# Disclosures

## Principal functionality developed for the Hackathon

All of it. `SKILL.md` and every reference file were written for this Hackathon, between 22 October and the submission date:

- the claim, inventory and parcel workflow over five registered experts;
- the evidence rules: sightings and possible sightings, device photos, receipt matching, values, the at-home test, and the handling of instruction-like text found inside evidence;
- the dossier layout with its SHA-256 exhibit table, the hashed camera log and the hash of the previous inventory;
- the read-first, write-once approval design.

## AI tools used

| Tool | Principal use |
|---|---|
| Claude Code with Claude Opus 5.5 | writing `SKILL.md` and the reference files, the local rehearsal harness and its tests, and the project documents |
| Qwen-Image 2.1 | generating the photos of the validation household |
| Qwen Plus (`qwen-plus-2025-04-28`, Qwen3 series) and `qwen3-vl-plus` on Alibaba Cloud Model Studio | playing the assistant, the experts and the visual checks in the rehearsal, on the validation household only |
| Gemma 4 26B-A4B, run locally through llama.cpp | building the photo index of the validation households |

## Third-party components in the package

None. The package contains only Markdown files written for this Skill. It calls no external service and bundles no library, model, script or binary.

## Runtime dependencies on the NAS

| Component | Source | Used for |
|---|---|---|
| Uliya and its registered experts `file-agent`, `photo-agent`, `document-agent`, `knowledge-agent`, `security-monitor-agent` | UGREEN UGOS | every NAS operation |
| CLI capabilities `file-workflow`, `ug-filesystem`, `ug-photo`, `ug-document`, `ug-knowledge`, `ug-surveillance` | UGREEN capability catalog 2.0.0 | the actions listed in `SKILL.md` |
| The NAS local AI model selected in Uliya | UGREEN UGOS | planning, visual checks, OCR and extraction |

## Data flows

- All reads and writes stay on the NAS, through the registered experts.
- Outputs: one new claim folder in the user's home folder (copies of the exhibits, the camera log and `CLAIM-DOSSIER.md`) and, on request, one album.
- No sharing link is created and nothing is sent outside the NAS. The user decides what to send to an insurer.
- When Uliya is configured with an online model, the Skill asks the user before step 2, as described in the evidence rules.
- The rehearsal, which is not part of the package, sent only the validation household, built for this project with no personal data, to Alibaba Cloud Model Studio.

## Test data

The validation household contains no personal data:

- photos generated as test fixtures with Qwen-Image 2.1, used under the Qwen Research License Agreement (research and evaluation use), then given EXIF capture times, devices and GPS for the tests;
- documents rendered with ReportLab (BSD licence) and Pillow (MIT-CMU licence).

The test data is not part of the package.
