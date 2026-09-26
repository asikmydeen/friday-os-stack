# Secrets

**Status: draft.**

- No secret ships baked into an image. First boot generates the machine id
  and application secrets before the owner is asked anything.
- Connections (integrations, app API keys) are stored as a reference to a
  secret, never the secret value itself, alongside the object that uses it.
- The Board never echoes a stored secret back once it has been entered.
