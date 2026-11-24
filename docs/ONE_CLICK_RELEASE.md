# One-click release (GitLab -> GitHub)

GitLab is the source of truth. GitHub is the public download surface. The
shared CI template is unchanged. No scientific code or existing release is
modified by enabling this workflow.

## One-time configuration (Maintainer)

1. Protect the main branch and tags matching v*. Limit tag creation to
   Maintainers (or the designated release automation identity). Check that
   no broader wildcard rule permits unauthorized creation.
2. Use a project access token with Maintainer role and api scope if available
   on your GitLab plan. Prefer a project-scoped fine-grained personal token
   with repository-tag, pipeline/job read and create, and release permissions
   if available. Avoid broad personal credentials; if neither scoped option
   is available, evaluate a dedicated, project-only release account before
   enabling automated tagging.
3. In Settings > CI/CD > Variables, add GITLAB_RELEASE_TOKEN (Variable,
   Masked and hidden, Protected, expansion disabled, environment scope
   release/*). Do not paste it into job parameters, commits or chat.
4. In GitHub create a fine-grained PAT restricted to soil-mir-PLSR-app,
   Contents: Read and write. Add GITHUB_RELEASE_TOKEN to GitLab with the
   same visibility/protection settings but environment scope release/publish.
5. If supported by your GitLab plan, protect release/tag and release/publish
   environments and authorize only designated release maintainers. Keep
   credentials out of ordinary test jobs. Check token expiration periodically.
   Do not enable debug tracing on release jobs.

## Each new version

- On a development branch bump pyproject.toml and src/soil_mir/__init__.py
  together, and add RELEASE_NOTES_vX.Y.Z.md. Merge only after CI succeeds.
- On the successful protected main pipeline, run create_release_candidate
  and confirm. It verifies the tested SHA, creates the next rc tag, and
  launches or reuses the tag pipeline. An already released version is skipped.
- Download both candidate archives from the RC pipeline and conduct desktop
  and scientific acceptance. For a fix, merge new code then create a new RC.
- On the accepted RC pipeline, run promote_release_candidate and confirm.
  This verifies both packaging jobs, the candidate and current main SHA,
  then creates the final tag from precisely that candidate.
- The protected final tag pipeline packages both platforms and runs
  publish_official_release automatically. It checks approval provenance,
  mirror SHA, version notes, both package files, and asset SHA-256 digests.
  It creates a draft, uploads Mac, Windows and SHA256SUMS.txt, verifies the
  three assets, publishes the GitHub release as latest, then records the
  GitLab release with public links.
- Never hand-create a final tag for this automated flow: it must be created
  by promotion. Do not move existing tags or delete published releases.

## Recovery

Retry a failed publish job while artifacts are available (30 days).
A matching managed draft reuses valid assets and repairs incomplete uploads.
A matching managed public release is checked but not changed. A different
SHA, unmanaged release, or newer official release blocks publication.
If a tag pipeline fails, retry its failed jobs, not the tag creation job.
If the mirror is slow, use GitLab's mirror update or retry publication.
If a package or release credential expires, renew the credential or retry the
packaging pipeline as appropriate. No release is made public if asset
verification fails. GitLab recording can be retried after GitHub publication.
Do not use the already released v0.2.4 to live-test this automation. The first
new version needs genuine release acceptance; offline tests mock APIs.
