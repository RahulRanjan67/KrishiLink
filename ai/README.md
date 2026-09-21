# Future AI Interfaces

The `ai/` directory contains intentionally disabled interfaces for possible future AI-assisted features such as:

- buyer-requirement parsing
- natural-language inventory search
- deterministic match explanations
- guided help

These modules are **not part of the required runtime path** of the current prototype.

Any future AI-generated value should pass through the same Pydantic validation, authorization checks, and business-rule layer as normal user input rather than directly changing application state.
