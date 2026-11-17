---
project: <name>
updated: YYYY-MM-DD
scanned_ref: <git short sha the scan ran on>
language: <project.language>
---

# Project map — <name>

<!-- Keep these headings: knowledge is indexed per section. Write in project.language.
     Cite file:line or document paths. Unknown → "unknown — ask <PO/dev>". -->

## Product overview

<What the product does, for whom, main user journeys (3–6 bullets). Link the README / agent files instead of copying them.>

## Modules and features

| Module / feature | What it does | Code | Docs | Owner |
|---|---|---|---|---|

## Screens and routes

| Screen / route | Purpose | Roles | Code |
|---|---|---|---|

## API endpoints

<Source: OpenAPI file(s) … or code scan. Group by tag/module; mark auth required.>

| Method | Path | Purpose | Auth / roles | Code or spec |
|---|---|---|---|---|

## Roles and permissions

| Role | Can | Cannot | Defined in |
|---|---|---|---|

## Data entities and states

| Entity | Key fields | States and transitions | Rules | Defined in |
|---|---|---|---|---|

## Integrations

| Service | Used for | Test mode / sandbox | Config (env var names only) |
|---|---|---|---|

## Environments

| Name | URL | Writes allowed | Data / reset notes |
|---|---|---|---|

## Feature flags

| Flag | Controls | Default | Where checked |
|---|---|---|---|

## Existing tests and CI

<Frameworks, folders, how to run, CI jobs and what they gate, coverage gaps you noticed.>

## Glossary

| Tiếng Việt | English | Meaning in this product |
|---|---|---|

## Risky areas

| Area | Why risky | Evidence | Test focus |
|---|---|---|---|

## Sources

- <path or URL> — <what it contributed>
