## The Intelligence Service

A FastAPI service that powers a WhatsApp-based customer feedback analyzer. It integrates with Twilio (WhatsApp) for messaging, OpenAI for conversation analysis, AWS DynamoDB for chat/session storage, Amazon S3 for media storage, PostgreSQL (via SQLAlchemy) for structured data, and provides a simple HTTP API.

### High-level architecture
- **API layer (FastAPI)**: `app.py` boots the app and wires routes via `src/routes`.
- **Routes**:
  - `GET /health/` health check.
  - `POST /reply/` triggers a WhatsApp reply workflow for a given `sender_id`.
- **Services**:
  - `ChatService` (`src/services/chat_service.py`): orchestrates conversation flow, persists chats to DynamoDB, sends messages via Twilio, uploads media to S3, and persists structured feedback to PostgreSQL.
  - `LLM` (`src/services/llm_service.py`): uses OpenAI to analyze conversation context and return a strict JSON with reply and extraction signals.
- **Data stores**:
  - DynamoDB tables: `sessions` (active/completed sessions) and `chats` (messages).
  - S3 bucket: stores user-uploaded media under `feedback-media/…`.
  - PostgreSQL: stores models `User`, `Feedback`, `Job`, `JobConfig`, `Topic`.
- **Configuration**: `config.py` loads from environment variables, falling back/merging with AWS Secrets Manager when not running locally.
- **Logging**: `src/utils/logger.py` provides a small JSON-structured logger wrapper used across the app.

### Architecture

```mermaid
flowchart LR
  WA["WhatsApp User"] --> Twilio["Twilio WhatsApp"]
  Twilio --> Nginx["Nginx + SSL"]
  Nginx --> FastAPI["FastAPI /reply"]
  FastAPI --> ChatService["ChatService"]
  ChatService --> OpenAI["OpenAI LLM"]
  ChatService --> DynamoDB[(DynamoDB: sessions & chats)]
  ChatService --> S3[(Amazon S3: feedback-media)]
  ChatService --> Postgres[(PostgreSQL)]
  ChatService --> Twilio
  Twilio --> WA
  Secrets["AWS Secrets Manager"] -.-> FastAPI
  GH["GitHub Actions"] --> EC2[(EC2 Uvicorn service)]
  EC2 --> Nginx
```

### Request flow (reply)
1. `POST /reply/` receives `{ sender_id, message }`.
2. `ChatService.get_user_unresolved_session_message` reads the active session and messages from DynamoDB.
3. `LLM.analyze_conversation` summarizes context and returns: `reply`, flags (e.g., `is_feedback_session_complete`, `should_persist_reply`, moderation flags), and extracted `product_name`, `feedback`, `media_urls`.
4. Session is updated (completed/limited/reopened) as needed.
5. A WhatsApp message is sent via Twilio, chat is optionally persisted to DynamoDB, and when feedback is complete any referenced media is fetched from Twilio, uploaded to S3, and a `Feedback` row is saved in PostgreSQL.

### Endpoints
- `GET /health/`
  - Returns: `{ "status": "healthy" }`

- `POST /reply/`
  - Body: `{ "sender_id": string, "message": string }`
  - Side effects: may send a WhatsApp message, write to DynamoDB, upload media to S3, and store feedback in PostgreSQL.
  - Returns: `{ "session_id": string, "message_id": string, "status": "sent" }` on success.

### Configuration
Configuration values are loaded from environment variables in local mode (`FLASK_ENV=local`) or from AWS Secrets Manager otherwise. Keys used:
- `OPENAI_API_KEY`
- `INTELLIGENCE_API_SECRET` (reserved for future authentication)
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_WHATSAPP_FROM` (e.g., `whatsapp:+14155238886` or just the phone number; code normalizes it)
- `DATABASE_URL` (SQLAlchemy URL, e.g., `postgresql+psycopg2://user:pass@host:5432/db`)
- `S3_BUCKET_NAME` (defaults to `theunce-project` in code)

AWS Region is assumed `us-east-1` for DynamoDB, S3, and Secrets Manager.

Example `.env`:
```bash
OPENAI_API_KEY=sk-...
INTELLIGENCE_API_SECRET=...
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/unc_intelligence
FLASK_ENV=local
S3_BUCKET_NAME=theunce-project
```

### Data models (PostgreSQL via SQLAlchemy)
- `User`: `id`, `email`, `full_name`, `hashed_password?`, `is_active`, timestamps.
- `Feedback`: `id`, `sender_id`, `product_name`, `feedback_text`, `media_urls[]`, timestamps.
- `Job`: `id`, `job_name`, `last_processed_id`, `status` (processing|completed|failed), timestamps.
- `JobConfig`: `id`, `config` (JSON).
- `Topic`: `id`, `label` (unique), `description?`, `is_active`, timestamps.

Note: Alembic migrations are not included; provision tables yourself or add migrations before first run.

### Services
- `ChatService`
  - Twilio client for WhatsApp sends.
  - DynamoDB `sessions`/`chats` accessors and transformations.
  - S3 media upload (`feedback-media/{message_sid}/{media_sid}.{ext}`).
  - Persists `Feedback` entities to PostgreSQL with injected SQLAlchemy `Session`.
  - Uses a thread pool for network-bound operations from async contexts.

- `LLM`
  - Uses OpenAI `chat.completions.create` with `response_format=json_object`.
  - Applies a strict system prompt to produce a single JSON blob including classification/moderation signals and reply guidance.
  - On unsafe/irrelevant content toggles `should_persist_reply=false`, sets a temporary limit window, and requests session reopen.

### Local development
1. Create and populate `.env` as above (set `FLASK_ENV=local`).
2. Install dependencies:
   - `python3 -m venv venv && source venv/bin/activate`
   - `pip install --upgrade pip && pip install -r requirements.txt`
3. Ensure PostgreSQL is running and `DATABASE_URL` is valid; create tables for models.
4. Run the app:
   - Option A (default ports and workers in `app.py` when executed directly):
     - `python app.py` (starts on `0.0.0.0:8000` with computed workers)
   - Option B (dev script):
     - `bash start_app.sh` (loads `.env` and runs uvicorn on port `8200`)

### Deployment
GitHub Actions workflow `.github/workflows/deploy.yml` deploys to an Ubuntu EC2 instance on pushes/merged PRs to `main`:
- Provisions system packages, Python venv, installs dependencies
- Sets up a systemd service `feedback-intelligence` to run Uvicorn on port 8000
- Configures Nginx reverse proxy at `intelligence.jurhua.com` with Certbot for SSL
- Installs and configures Amazon CloudWatch Agent to forward app and Nginx logs

Required repository secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `INTELLIGENCE_EC2_IP`, `INTELLIGENCE_EC2_SSH_KEY` (base64 PEM), etc.

### Directory structure
```
feedback-intelligence/
  app.py                  # FastAPI app bootstrap
  config.py               # Env/Secrets Manager loader
  requirements.txt        # Python dependencies
  start_app.sh            # Dev runner (port 8200)
  src/
    routes/               # FastAPI routers (health, reply)
    services/             # ChatService, LLM (OpenAI)
    models/               # SQLAlchemy models
    database/             # SQLAlchemy engine/session
    utils/logger.py       # JSON-structured logger
```

### External dependencies
- Twilio WhatsApp API (send-only from this service)
- AWS: DynamoDB (`sessions`, `chats`), S3 (media), Secrets Manager (optional), CloudWatch (deploy)
- OpenAI API (model default `gpt-5-nano`)
- PostgreSQL for relational storage


---

For issues or deployment concerns, see the workflow at `/.github/workflows/deploy.yml` and logs in CloudWatch (`/feedback-intelligence/*`).
