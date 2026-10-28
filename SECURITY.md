# Security

Imagine Studio is a localhost application for one trusted local user. It is not
prepared for a public network deployment. Do not expose its port through a public
proxy without a separate security review. Agent tokens and provider sessions are
private local credentials; browser consent and generation approval remain required.

Do not publish suspected secrets, state dumps, prompts containing private material,
or full provider error payloads in GitHub issues. Contact the repository owner
privately through your established channel. A public disclosure address has not
yet been designated. If a credential was exposed, revoke/rotate it before cleaning
Git history. Ignore rules do not remove already committed material.
