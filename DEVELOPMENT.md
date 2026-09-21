# Development Notes

## Project context

KrishiLink was created while exploring **Smart India Hackathon Problem Statement 26132 — “Strengthening market linkages and price discovery for farmers.”** The goal was to turn a broad problem statement into a small but coherent working prototype that could demonstrate an end-to-end farmer/FPO/buyer transaction workflow.

## Development approach

This project used an **AI-assisted development workflow with Antigravity and AI development tools**.

AI assistance was used extensively for implementation generation, repetitive coding, library exploration, and iteration. Human contribution focused on directing and refining the prototype, including:

- breaking down the problem statement into practical workflows
- planning the feature set and user journeys
- shaping the overall application architecture
- deciding which prototype features to implement or leave for future work
- designing the structure and layout of the HTML pages
- reviewing and proofreading generated HTML and CSS
- refining functions and business rules
- fixing straightforward implementation errors
- testing workflows and correcting issues found during testing
- reviewing the final prototype for consistency and scope

The resulting code should therefore be understood as **AI-assisted prototype work with human direction and refinement**, rather than as either a fully hand-written project or a completely autonomous AI output.

## Scope discipline

The prototype intentionally focuses on a demonstrable transaction workflow instead of attempting to implement every capability in the SIH problem statement. Features that would require live external systems—such as real mandi feeds, payment gateways, logistics providers, storage networks, or external buyer verification—remain outside the current scope.

## Reproducibility

The repository uses a small SQLite database and seeded demonstration accounts so the main workflow can be reproduced locally without external services.

The `.env.example` file documents the required session configuration. Real credentials, local environment files, and generated databases are excluded through `.gitignore`.

## Status

This is an experimental prototype. The current implementation is suitable for demonstration, code exploration, and further iteration; it is not intended for production deployment without substantial security, authorization, infrastructure, and integration work.
