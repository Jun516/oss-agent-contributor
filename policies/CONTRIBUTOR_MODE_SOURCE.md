# Contributor Mode source and user-authorized override

Original: `helson-resume-skill/references/modes/contributor.md` in the supplied ZIP.

The user **explicitly superseded** that document's step 5 / 6 **per-external-write approval** requirements and requested unattended PR submission from their `Jun516` identity.

This repository therefore has the owner-authorized `publication_policy=preauthorized`. A scoped automated GitHub chain (fork if missing, push a single short-lived issue branch, create one PR) may proceed **without separate chat confirmation** after mandatory checks. This does **not** override host authorization, required GitHub credentials, maintainer contribution policies, safety controls or optional publisher suspension.

Unchanged contribution requirements: >= 5K Stars, fresh and licensed repository, repo contribution rules, real issue and reproduction, no assigned/in-progress work, no duplicate PR, a single minimal change, independent tests, SHA-bound patch and recorded PR evidence. Do not automatically merge, close issues, post follow-up comments, bypass CI, or edit privileged files. Never invent a successful PR.

Restrictions: at most 2 new PRs in a rolling 24 hours; one PR candidate per scan; staging/verification have no write token, publishing has no untrusted execution; `PAUSE_AUTOPUBLISH=true` immediately stops new publishing. If API or preflight validation fails, fail closed.
