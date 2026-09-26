# Shared GitLab CI template

This directory contains the reusable CI configuration for Python applications in the
`haidaitoubaba-group` namespace.

## Use from another project

Create a small `.gitlab-ci.yml` in the consuming project:

```yaml
include:
  - project: "haidaitoubaba-group/soil-mir-plsr-app"
    ref: "main"
    file: "/.gitlab/ci/python-app.yml"

variables:
  CI_PYTHON_VERSION: "3.11"
  CI_INSTALL_CMD: 'python -m pip install -e ".[test]"'
  CI_LINT_PATHS: "."
  CI_TEST_CMD: "pytest -q"

  # Set this only for Streamlit projects.
  CI_STREAMLIT_APP: "app/Home.py"

  # Optional project-specific validation.
  CI_EXTRA_VALIDATE_CMD: ""

  # Optional release packaging. Leave blank to disable a package job.
  CI_MAC_BUILD_CMD: ""
  CI_MAC_VERIFY_CMD: ""
  CI_MAC_ARTIFACT_PATH: "dist/*.tar.gz"

  CI_WINDOWS_BUILD_CMD: ""
  CI_WINDOWS_VERIFY_CMD: ""
  CI_WINDOWS_ARTIFACT_PATH: "dist/*-windows.zip"
```

## What the template standardizes

- Merge-request pipelines without duplicate branch pipelines.
- Interruptible jobs so superseded pipelines can be canceled.
- A shared pip cache.
- One quality job for Ruff, pytest, and an optional Streamlit health check.
- Validation and quality jobs are skipped for release tags.
- Mac and Windows packaging run only for tags and only when their build commands are configured.
- Release artifacts expire after 30 days.

## Update behavior

Projects that reference `ref: "main"` automatically use the newest shared template on
their next pipeline. This is convenient, but a bad template change can affect every
consumer. Template changes should therefore be made on a branch, validated in a consuming
project, and merged only after the pipeline passes.

If a project needs a frozen CI configuration, change `ref` from `main` to a template
tag or commit SHA.
