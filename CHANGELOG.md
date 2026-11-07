---
doc_id: fusion-k12-teacher/changelog
product: fusion-k12-teacher
class: app
entry: guided-ui
doc_type: changelog
title: { zh: "Fusion-K12-Teacher 变更记录", en: "Fusion-K12-Teacher changelog" }
audience: engineer
status: draft
version: 2.2.7
updated: 2026-11-07
owner: @dahai
source_of_truth:
  - CHANGELOG.md
  - pyproject.toml
---

# Changelog

## 2.2.7

- docs: adopt fusion docs-system v1.1 contract (app x guided-ui) — add docs/product-page.md, docs/get-started.md, docs/troubleshooting.md, docs/img/web-login.png, ci/validate_docs.py, .github/workflows/docs.yml; add 12-key frontmatter to existing first-party markdown (PR #39).
- fix: resolve legacy port env through `_legacy_port_env` helper instead of inline read.

## 2.2.6

- web: align web console with union shell UI spec via SDK theme/i18n channels (issue #38).

## 2.2.5

- Register union web menu taxonomy: sort 39 in shell manifest (issue #37).

## 2.2.4

- Fail closed on cluster-mode repository misconfiguration (issue #36).

Historical versions before 2.2.4 are tracked in git history and the module sections of README.md (v0.3 standards/differentiation, v0.4 analytics, v0.5 agent, v0.6 safety, v1.0 desensitize, v2.0 enterprise infra, v2.1 course platform/classroom, v2.2 digital human, v2.3 teacher identity).
