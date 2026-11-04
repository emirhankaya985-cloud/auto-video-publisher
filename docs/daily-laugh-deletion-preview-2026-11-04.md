# Daily Laugh Lab post inventory

The November 4 request includes deleting the account's posts. This marker starts a single read-only inventory on `main` before deciding the exact deletion scope. The report enumerates the configured Daily Laugh Lab Facebook Page, its linked Instagram profile, the exact YouTube channel, and the `dail.ylaughlab` Threads profile.

The public workflow artifact keeps counts, account identities, and SHA-256 fingerprints of sorted unique ID sets. It omits individual content IDs, captions, titles, access tokens, and private YouTube links. Facebook published posts and video objects may overlap. Instagram Stories and Threads replies fall outside the selected profile edges. A completed inventory means those visible edges were exhausted at the observed time. The report records available permission evidence separately from the inventory.

The workflow uses the existing account credentials, does not alter publication state, and makes zero deletion attempts. An execution step must recheck the account identities and current inventory before using a confirmed selection.
