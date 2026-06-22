# Redrob Candidate Ranking System

An AI-powered recruiter relevance prediction engine that ranks candidates by understanding skills, experience, career trajectory, behavioral signals, and role fit rather than relying on keyword matching.

## Architecture

This system uses a highly robust, routed multi-provider LLM infrastructure to prevent rate limits and outages from halting execution.

## Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Populate the `.env` file with your available API keys for the configured providers (Gemini, Groq, Cerebras, GitHub Models, OpenRouter).

## Documentation

Detailed technical specifications and architectural decisions are documented within the codebase:
- **[Phase 1: JD Intelligence Engine](docs/phases/phase01_jd_intelligence.md)**: Deep dive into the multi-lens prompt extraction, Pydantic schemas, and mathematical median aggregation.
- **[LLM Routing Infrastructure](docs/architecture/llm_routing_infrastructure.md)**: Deep dive into the phase-aware routing, Pydantic validation retry loops, and SHA-256 caching mechanisms.