# DripPop

**See the drip. Tap the pop. Try it on.**

An Android-first virtual try-on concept: tap a floating button over Instagram, choose clothing from the visible post or reel frame, and see a personal preview in an expandable overlay above the same feed.

## Start here

- [Agent handoff](HANDOFF.md) — entry point for a fresh implementation agent.
- [Full PRD](docs/PRD.md) — product requirements, complete stack, contracts, acceptance criteria and delivery stages.
- [Agent instructions](AGENTS.md) — documentation and working conventions.

The plan is organized into **setup**, **parallel feature implementation**, and **integration/testing**, with sub-agent ownership and dependencies. Three.js is included as a stretch feature for a rotatable 3D preview.

## Research

- [Overlay/platform and competitive research](docs/research/overlay-research.md)
- [Tech stack and durable backend research](docs/research/tech-stack.md)
- [Archived hackathon concept research](docs/research/idea-research.md)

The PRD is authoritative where earlier notes contain provisional findings. Research references and limitations are preserved for later verification.

## Current status

This repository contains the specification and research. Application implementation has not started.

The recommended baseline is Kotlin/Jetpack Compose on Android, FastAPI, Gemini localization, YouCam Clothes V4, and Firebase/GCP for authenticated durable processing. Physical-phone capture/overlay behavior and real-provider fidelity still need validation. Generated images are appearance previews, not measurements of physical fit.

Planned for the [YouCam API Skin AI & eCommerce VTO Hackathon](https://youcam-api-skin-ai-ecommerce.devpost.com/).
