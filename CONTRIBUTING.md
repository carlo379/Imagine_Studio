# Working on Imagine Studio

Use mock mode and isolated temporary storage. Do not commit credentials, local
state, generated production media, dependency folders or private customer data.
Never use a live writer or media provider in automated tests. Local fixture
rendering by FFmpeg and Canvas is expected.

For full offline verification, run `sh setup.sh` in subscription-tester to fetch
the pinned Hermes auth source (no account or live calls are needed). Then run `python3 scripts/verify.py` from the root.
Rebuild frontend changes with `npm run build` in `subscription-tester/`. Include
all referenced hashed chunks and the manifest. For API changes, update OpenAPI,
the agent contract, documentation and contract-drift tests together. Prompt
writing changes must use the model guides in `docs/prompting-guides/`.

Before committing, run `git diff --check` and review staged paths. Before a first
upload, install Gitleaks 8.30.1+ and run `python3 scripts/check_secrets.py` to scan
Git history and eligible source with redaction. Run `python3 scripts/check_docs.py`
for local documentation link targets. Never post
raw scanner output containing a credential. Do not grant a license for third-party
materials or claim rights to production assets on someone else's behalf.
