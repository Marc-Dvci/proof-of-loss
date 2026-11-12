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
- **Data:** two household archives built for these tests, with no personal data. Only they reached the cloud models.

## Evaluation

Six recorded rehearsal cases, all on the submitted Skill, scored against ground truth committed before the first run. The figures are in [`evidence/final/summary.json`](../evidence/final/summary.json), and `python tools/replay.py all` reproduces them with no model.

| Measure | Result |
|---|---|
| Expected photos of each item in the claim folder | 49 of 52 |
| Photos taken by the stolen camera in the claim folder | 6 of 6 |
| Expected receipts in the claim folder | 11 of 12 |
| Serial numbers found | 8 of 8 |
| Prices copied exactly | 10 of 10 |
| Camera events of the incident window cited | 10 of 10 |
| Listed hashes that match their files | 34 of 34 |
| Look-alike photos or unrelated receipts in a claim folder, all six cases | 0 |
| Totals or amounts that no document states | 0 |
| Writes before the user's answer, all six cases | 0 |
| Injected instruction followed | 0 |

Household B is held out: it was run and reported, and the Skill was never changed because of it.

## Human oversight

- Steps 0 to 5 only read. The draft goes to the user, who keeps or removes exhibits.
- Each write passes the platform's approval. A declined approval leaves the NAS unchanged.
- Every draft lists its possible photos with the reason, such as a shop display, a hotel room or another colour, and leaves them out unless the user keeps them.
- Every claim file names its gaps, so the person sending it sees what is weak.

## How a correction is made

The user removes an exhibit in the draft, or deletes the claim folder and runs the Skill again. A new run makes a new folder and leaves the old one as it was. The Skill changes no file outside the claim folder.

## What the NAS test day validates

- Photo recall on the NAS's own AI Album index and model, with the burglary of the [test plan](../skill/proof-of-loss/references/test-plan.md).
- The yearly inventory run twice: a new dated folder, the first left as it was, the previous dossier's hash recorded.
- What `event-evidence` returns for a snapshot export, so each snapshot can be copied next to the camera log.
