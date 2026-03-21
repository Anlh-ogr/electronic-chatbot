# MVP chat context notes

This MVP separates UI history from inference context:

- `messages`: for chat history rendering and replay in UI.
- `chat_summaries`: compact context to reduce token usage when history grows.
- `memory_facts`: durable facts and preferences for personalization.
- `document_chunks`: semantic retrieval context with pgvector.

## Suggested runtime flow

1. Save incoming user message into `messages`.
2. Retrieve context in this order:
   - latest `chat_summaries`
   - active `memory_facts`
   - top-k `document_chunks` by vector similarity
3. Call model.
4. Save assistant response into `messages`.
5. If message count crosses threshold, regenerate summary into `chat_summaries`.

## Free-tier optimization

- Use summary refresh every N turns (e.g. 8-12).
- Cap chunk retrieval (e.g. top_k=5).
- Store token estimates in summary to trigger compression early.
- Apply retry and fallback for external retrieval providers.
