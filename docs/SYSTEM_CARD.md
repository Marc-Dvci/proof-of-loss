# System card: Proof of Loss

## What it is for

Proof of Loss is an Uliya Skill for a household that has lost goods to a burglary, flood, fire or a missing parcel. It gathers evidence the household already holds on its UGREEN AI NAS into a claim folder the household can send to an insurer. An inventory mode records valuables before anything happens.

It informs a decision about money: an insurer reads the dossier when it settles a claim. The dossier is a set of copies and facts. The insurer and the household keep the decision.

## What it is not built for

- Deciding whether a claim is valid, or what an item is worth. It never estimates a price and does no arithmetic on prices.
- Identifying people. A person is named only when the camera's own face library returns a known name.
- Certifying that a photo is authentic. A hash fixes a file at the moment it was copied; capture times are the EXIF values as recorded.
- Writing, editing or re-dating any receipt, photo, timestamp or value. Step 0 declines such a request.

## Models and data

- **On a NAS:** the model selected in Uliya, and the NAS's own AI Album index. The Skill calls no external service.
- **In the rehearsal:** Qwen Plus (`qwen-plus-2025-04-28`, Qwen3 series) played the assistant and the experts, and `qwen3-vl-plus` answered the visual checks, both on Alibaba Cloud Model Studio. Gemma 4 26B-A4B built the photo index once, locally.
- **Data:** two synthetic households with fictional people, brands, merchants, serial numbers and plates. Only this synthetic data reached the cloud models.

## Evaluation

Five recorded rehearsal cases, scored against ground truth committed before the first run. The figures are in [`evidence/final/summary.json`](../evidence/final/summary.json), and `python tools/replay.py all` reproduces them with no model.

| Measure | Result |
|---|---|
| Exhibit hashes in the dossiers that match the files | 31 of 31 |
| Serial numbers found | 5 of 5 |
| Prices copied exactly | 6 of 6 |
| Camera events of the incident window cited | 10 of 10 |
| Photos taken by the stolen camera in the claim folder | 3 of 3 |
| Expected photos of each item in the claim folder | 20 of 30 |
| Expected receipts in the claim folder | 5 of 7 |
| Writes before the user's answer, all five cases | 0 |
| Amounts that no document states | 0 |
| Injected instruction followed | 0 |
| Decoy photos in a claim folder | 1, a hotel TV |

Household B is held out: it was run and reported, and the Skill was never changed because of it.

## Human oversight

- Steps 0 to 5 only read. The draft goes to the user, who keeps or removes exhibits.
- Each write passes the platform's approval. A declined approval leaves the NAS unchanged.
- Every claim file names its gaps and its possible sightings, so the person sending it sees what is weak.

## How a correction is made

The user removes an exhibit in the draft, or deletes the claim folder and runs the Skill again. A new run makes a new folder and leaves the old one as it was. The Skill changes no file outside the claim folder.

## Known limits

- Recall follows the photo index and the model's visual check: 20 of 30 expected photos reached the folder in the rehearsal.
- A vision model can misread a small logo, and the dossier repeats what it reported in its "what is visible" column. Brands come from receipts and labels.
- On the rehearsal model, inventory mode often skipped the draft question. The platform's approval still gated each write, and core test 2 of the [test plan](../skill/proof-of-loss/references/test-plan.md) checks this mode on the NAS.
