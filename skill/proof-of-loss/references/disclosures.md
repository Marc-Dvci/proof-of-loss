# Disclosures

## Principal functionality developed for the Hackathon

All of it. `SKILL.md` and every reference file were written for this Hackathon, between 22 October and the submission date:

- the claim, inventory and parcel workflow over six registered experts;
- the evidence rules: confirmed sightings, device photos, receipt matching, values, the at-home test, and the handling of instruction-like text found inside evidence;
- the dossier layout with its SHA-256 exhibit table;
- the read-first, write-once approval design.

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
- Outputs: one claim folder in the user's home folder (copies of the exhibits plus `CLAIM-DOSSIER.md`) and, on request, one album.
- No sharing link is created and nothing is sent outside the NAS. The user decides what to send to an insurer.
- When Uliya is configured with an online model, the Skill asks the user before step 2, as described in the evidence rules.

## Test data

The validation household is synthetic and contains no personal data:

- photos generated as test fixtures with Qwen-Image 2.1, used under the Qwen Research License Agreement (research and evaluation use), then given synthetic EXIF;
- documents rendered with ReportLab (BSD licence) and Pillow (MIT-CMU licence).

The test data is not part of the package.
