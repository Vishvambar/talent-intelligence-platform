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