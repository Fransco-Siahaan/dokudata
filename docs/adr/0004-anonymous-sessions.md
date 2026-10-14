# ADR 0004: Anonymous sessions and signed URLs instead of accounts

- Status: accepted
- Date: 2026-10-11

## Context

Reviewers must try the demo without signing up (US-10), but visitors must never see each other's uploads, and IDs must not be guessable.

## Decision

- The browser generates a random 24-byte token and sends it as `X-DokuData-Session`. The server stores only `sha256(token)` as the document owner and returns 404 for documents of other owners.
- Document IDs are random (`doc_` + 96 bits), never sequential.
- Images, originals, exports and the SSE status stream are served through short-lived HMAC-signed URLs, because `<img>` and `EventSource` cannot send headers.
- Rate limits per IP on uploads and demo runs, a daily document quota per session, a separate daily quota for LLM engines, and deletion after 24 hours.

## Consequences

- Clearing browser storage loses access to one's documents (they still expire after 24 h).
- The in-process rate limiter is per API replica; a multi-replica deployment should move it to Redis.
