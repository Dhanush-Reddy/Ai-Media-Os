# Remote Approval Access

Remote approval is intentionally split from media generation. The SQLite database, filesystem,
workers, ComfyUI, Chatterbox, Ollama, and FFmpeg remain on the production laptop. Remote clients
may inspect review-safe summaries and submit approval decisions only through application services.

## Delivery sequence

1. Milestone 9E adds a private Telegram approval bot.
2. Milestone 9F adds an optional authenticated web approval API and static Netlify client.
3. Publishing and Shorts remain separate milestones.

## Telegram first

The bot runs on the laptop and uses Telegram Bot API long polling. This requires outbound HTTPS
only, so the laptop does not need an inbound port, public IP, webhook, or tunnel. The bot token is
an environment secret and the bot accepts commands only from configured Telegram user and chat
IDs.

Every callback carries a short-lived opaque action token. The backend resolves that token to one
pending approval, validates the expected project, content version or asset, current status, and
reviewer allowlist, then calls the existing approval, asset-review, or render-review service.
Telegram `update_id` plus the action token form the idempotency key so retries cannot apply a
decision twice. The bot never edits SQLite rows directly and never interprets a missing response
as approval.

Initial messages should support script summaries, image and thumbnail previews, narration and
render links or uploads, timeline summaries, warnings, and these actions:

```text
Approve
Reject
Request changes
Regenerate
Open dashboard
```

## Netlify client with a local backend

A Netlify-hosted static frontend cannot call `localhost` on the production laptop. The browser's
`localhost` always means the phone or computer running that browser. Remote web approval therefore
requires this path:

```text
Netlify static approval UI
  -> authenticated HTTPS approval API
  -> identity-aware access gateway
  -> outbound secure tunnel
  -> FastAPI on 127.0.0.1
  -> existing application approval services
  -> local SQLite and project files
```

The recommended public-web option is a Cloudflare Tunnel protected by Cloudflare Access. The
`cloudflared` process creates an outbound-only tunnel from the laptop; Access authenticates the
reviewer before forwarding requests. The backend must also validate the Access token and enforce
its own reviewer authorization. A private alternative is Tailscale Serve, which avoids a public
site and restricts the dashboard to devices in the user's tailnet.

The Netlify site should contain only static HTML, CSS, and JavaScript. It must not contain bot
tokens, tunnel credentials, service tokens, database files, project files, or permanent media
URLs. Review media is returned through ownership-checked endpoints using short-lived signed URLs.

## Required API hardening

Before Netlify deployment, add:

- Authentication and an explicit reviewer allowlist.
- Narrow read-only review endpoints and decision endpoints; do not expose general database CRUD.
- Short-lived sessions or signed action tokens with replay protection.
- Exact-origin CORS policy for the Netlify production hostname.
- CSRF protection for cookie-authenticated decisions.
- Rate limits, request-size limits, structured audit logs, and decision idempotency keys.
- Ownership checks and short-lived access for image, audio, thumbnail, and video previews.
- Laptop-offline and tunnel-offline states that fail closed and never queue an approval implicitly.

Netlify hosts only the interface. The application remains unavailable whenever the laptop,
FastAPI process, or secure tunnel is offline. No automatic publishing is introduced by either
remote approval channel.

