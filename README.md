# AI Message Router PoC

A containerised microservice that routes free-text user messages to the right department.
An **AI agent** running on a **local Ollama LLM** reads the message, picks one of five
departments and forwards the message by **calling its `send_email` tool**. The email is caught
by Mailpit and carries `Reply-To` set to the original sender.

```
POST /api/v1/messages  {"email": "jan.nowak@example.com", "message": "Nie działa mi komputer"}
        → agent (qwen2.5:3b on Ollama) calls send_email(department="help_desk", ...)
        → Mailpit: To: help-desk@example.com, Reply-To: jan.nowak@example.com
```

## Quick start

Requirements: Docker with Docker Compose v2, about 3 GB of free disk space and 4 GB of RAM for
the containers.

```bash
git clone https://github.com/Mikarrr/poc_email_classification.git
cd poc_email_classification
docker compose up -d
```

The first start builds the API image and downloads the model (`qwen2.5:3b`, 1.9 GB), so it takes
a few minutes depending on your connection (about 1.5 minutes on a fast one). `up -d` returns
once the model is pulled and the API container has started; the API answers a few seconds later.
Later starts take seconds, because the model stays in a Docker volume.

| What | URL |
|---|---|
| Swagger UI | http://localhost:8000/api/v1/docs |
| OpenAPI schema | http://localhost:8000/api/v1/openapi.json |
| Mailpit (caught emails) | http://localhost:8025 |

Check that all services are up: `docker compose ps` (`api`, `ollama` and `mailpit` are
`healthy`, `ollama-init` has `Exited (0)`).

## Try it

```bash
curl -X POST http://localhost:8000/api/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"email": "jan.nowak@example.com", "message": "Nie działa mi komputer"}'
```

```json
{
  "request_id": "4d2f781c-5498-467f-8e79-d1a79c81a4d8",
  "department": "help_desk",
  "routed_to": "help-desk@example.com",
  "fallback_used": false
}
```

Open http://localhost:8025: the new email is addressed to `help-desk@example.com` and has
`Reply-To: jan.nowak@example.com`. The same check from the terminal, through Mailpit's API
(needs [jq](https://jqlang.org/)):

```bash
curl -s http://localhost:8025/api/v1/message/latest \
  | jq '{to: .To[0].Address, reply_to: .ReplyTo[0].Address, subject: .Subject}'
```

More messages to try:

| Message | Expected department |
|---|---|
| `Chciałbym zgłosić urlop na jutro` | `kadry` |
| `Chcę zapisać się na szkolenie z Excela` | `human_resources` |
| `Serwer plików nie odpowiada od rana` | `it` |
| `Kto przyniósł dziś ciasto do biura?` | `other` |

The first request after a start can take a few seconds while Ollama loads the model into memory;
after that a request takes about 1 second on a recent laptop CPU.

## API

**`POST /api/v1/messages`**

| Field | Rules |
|---|---|
| `email` | a valid email address; becomes `Reply-To` of the routed email |
| `message` | free text, 1–5000 characters after trimming |

| Status | When |
|---|---|
| `200` | the message was routed; `fallback_used` is `true` when the agent failed and the message went to `other@example.com` |
| `422` | invalid input; nothing is sent |
| `503` | the mail server is unreachable; nothing could be sent |

**`GET /api/v1/health`** returns `{"status": "ok"}` and is used by the Docker healthcheck.

## Routing rules

The brief lists two HR addresses and two IT addresses, so the agent gets these definitions:

| Department | Address | Handles |
|---|---|---|
| `kadry` | kadry@example.com | HR paperwork: leave, sick leave, contracts, payroll, certificates, working time |
| `human_resources` | human-resources@example.com | people matters: recruitment, onboarding, training, benefits, conflicts |
| `help_desk` | help-desk@example.com | the sender's own device or account: computer, printer, password reset, mail client |
| `it` | it@example.com | systems and infrastructure: servers, network, VPN, access rights, new software, outages |
| `other` | other@example.com | anything else or unclear, and the fallback when the agent fails |

The rules live in the system prompt: [`src/email_classifier/prompts/system.md`](src/email_classifier/prompts/system.md).

## Architecture

```
                  ┌───────────────────────────── docker compose ─────────────────────────────┐
 HTTP client      │                                                                          │
 (cURL, Swagger)  │  ┌─────────────────┐   OpenAI-compatible API   ┌─────────────────────┐   │
       │  :8000   │  │ api             │ ────────────────────────▶ │ ollama              │   │
       └─────────▶│  │ python:3.12-slim│ ◀── send_email(...) call  │ qwen2.5:3b-router   │   │
                  │  │ FastAPI         │                           │ model in a volume   │   │
                  │  │ pydantic-ai     │                           └──────────▲──────────┘   │
                  │  └────────┬────────┘                                      │ pull once    │
                  │           │ SMTP :1025                         ┌──────────┴──────────┐   │
                  │           ▼                                    │ ollama-init         │   │
                  │  ┌─────────────────┐                           │ pull + tune threads │   │
                  │  │ mailpit         │──▶ web UI :8025           └─────────────────────┘   │
                  │  └─────────────────┘                                                     │
                  └──────────────────────────────────────────────────────────────────────────┘
```

Start order, enforced with healthchecks and `depends_on` conditions: `ollama` is healthy →
`ollama-init` pulls the model and exits → `mailpit` is healthy → `api` starts.

Request flow:

1. FastAPI validates `email` and `message`.
2. The agent sends the system prompt and the message to the model. The message is wrapped in
   `<message>` tags, with `<` and `>` escaped so that it cannot close or fake the tags.
3. The model calls `send_email(department, subject, reason)`.
4. The tool maps the department to its address, sets `Reply-To` to the sender, attaches the
   original message to the email body and sends it over SMTP.
5. If the model fails, times out or never calls the tool, the code sends the message to
   `other@example.com` itself.

## Architecture decisions

- **Python, FastAPI and pydantic-ai.** FastAPI gives typed request models and Swagger out of the
  box. pydantic-ai builds the tool schema from a typed Python function, talks to Ollama through
  its OpenAI-compatible API and can replace the model with a scripted fake in tests.
- **The model picks a department, never an address.** The `department` argument is an enum of the
  five departments. Anything else fails validation and the model is asked to try again, so an
  email can only go to one of the addresses from the brief.
- **`Reply-To` and the email body are set by code.** The tool has no parameter for an address or
  for the message text. The model writes only a subject and a one-sentence reason, so a message
  that tries to talk the model into something cannot change the reply address or the content.
- **`send_email` ends the agent run.** It is registered as the agent's output function, so the run
  finishes with that call. This saves a second model call that would only produce a closing text.
- **The fallback lives in code.** Whatever the model does, every valid request produces exactly one
  email. Only an unreachable mail server returns an error (`503`).
- **Mailpit instead of MailHog.** The brief allows any similar tool. Mailpit is maintained, has an
  arm64 image and an HTTP API to check recipients and headers.
- **`qwen2.5:3b` on CPU.** It was the most accurate and the fastest of three models tested on 21
  Polish messages (`qwen2.5:3b` 19/21, `llama3.1:8b` 17/21, `llama3.2:3b` 14/21) and runs on any
  machine without a GPU.
- **CPU threads are tuned.** By default llama.cpp uses every core. On CPUs with efficiency cores,
  such as Apple Silicon, that made generation about 30 times slower. `ollama-init` creates
  `qwen2.5:3b-router` with `num_thread` set to half of the cores.

## Known limitations

- A 3B model makes mistakes on borderline messages. On the 64 Polish test messages in
  [`tests/fixtures/routing_cases.jsonl`](tests/fixtures/routing_cases.jsonl) it routes 62
  correctly on CPU (96.9%), including all 21 messages of the held-out part (the prompt was
  tuned on the other 43). The two misses: "zaświadczenie o zatrudnieniu" goes to
  `human_resources` instead of `kadry`, and one injected instruction ("dział = other") still
  changes the department. An injection can never change the recipient list or `Reply-To`.
- About a third of the email subjects come out in English although the messages are Polish.
  Asking for the message language in the tool description did not help and lowered accuracy.
- One request is processed at a time by Ollama; this is a PoC, not a load-tested service.

## Configuration

Docker Compose reads these optional variables from the shell or from a `.env` file
(see [`.env.example`](.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `API_PORT` | `8000` | host port of the API |
| `MAILPIT_UI_PORT` | `8025` | host port of the Mailpit web UI |
| `MAILPIT_SMTP_PORT` | `1025` | host port of Mailpit's SMTP server |
| `OLLAMA_MODEL` | `qwen2.5:3b` | base model pulled by `ollama-init` |
| `OLLAMA_NUM_THREAD` | half of the cores | CPU threads used by the model |
| `LLM_TIMEOUT_SECONDS` | `120` | timeout of one model call |
| `MAIL_FROM` | `router@example.com` | sender of the routed emails |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

Example: `API_PORT=8080 docker compose up -d`.

**NVIDIA GPU** (Linux or WSL2 with the NVIDIA Container Toolkit):

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

## Development

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

| Command | What it does |
|---|---|
| `make install` | install dependencies and the pre-commit hook |
| `make test` | run the tests; no LLM, Docker or mail server needed |
| `make lint` | ruff (lint and format check) and mypy (strict) |
| `make format` | fix lint issues and format the code |
| `make cov` | run the tests with a coverage report |
| `make e2e` | send the 64 test messages to the running stack and report routing accuracy (needs `make up`) |
| `make run` | run the API locally with reload on port 8000 (needs Ollama on `localhost:11434` and an SMTP server on `localhost:1025`) |
| `make up` / `make down` | start / stop the Docker stack (`down` keeps the model volume) |
| `make logs` / `make ps` | follow the logs / show the containers |

The tests replace the LLM with pydantic-ai's `FunctionModel` and the mail server with a fake or
a local `aiosmtpd` server. They cover routing, `Reply-To`, invalid department names, a model that
answers with text or fails, the fallback, the HTTP errors and logs without message content.

`make e2e` checks the real stack: every message must produce exactly one email in Mailpit with
the sender as `Reply-To`, and at least 90% must reach the expected department. It prints the
accuracy per department and per split, and every miss. Options: `E2E_SPLIT=dev|holdout|all`,
`E2E_MIN_ACCURACY`, `E2E_API_URL`, `E2E_MAILPIT_URL`.

```
src/email_classifier/
├── config.py          settings from environment variables
├── departments.py     Department enum and target addresses
├── schemas.py         API request and response models
├── mailer.py          SMTP sender with Reply-To
├── agent.py           pydantic-ai agent, send_email, fallback
├── prompts/system.md  system prompt with the routing rules
└── api/app.py         FastAPI app under /api/v1
docker/ollama-init.sh  model pull and CPU thread tuning
tests/                 unit, integration and end-to-end tests, routing cases
```
