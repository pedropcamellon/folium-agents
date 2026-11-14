# Agent Instructions

- Start from the user or business outcome before proposing technical work.
- For each component, dependency, and design choice, explain why it is needed to deliver that outcome.
- Prefer the smallest solution that achieves the outcome; avoid technology-first scope and unnecessary infrastructure.
- Use an evals-first approach for agent workflows: define independent expected outcomes, representative failure cases, and explicit safety and quality gates before implementing behavior. Use production-grade evaluation discipline without treating POC results as proof of production readiness.
