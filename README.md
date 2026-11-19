# Multi-client AI agent platform - funnel core + LLM conversation (Phase 0/1a/2)

Telegram lead-conversion bot for a financial-education client, following the flow:
reel -> bot link -> name/phone -> questions -> free guide -> book call? -> sales call, or follow-ups day 1/3/7.

## Run on Windows PowerShell
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install PyYAML                                   # enough for tests and the simulator
python -m unittest discover -s tests -t .            # 40 tests
Copy-Item .env.example .env
python -m app.main check-config                      # lists what the client still has to provide
python -m app.main console --enable-followups        # chat with the bot in the terminal
python -m app.main console --llm mock                # also exercises the LLM agent loop (no API key)
```
Console commands: `:advance N` (jump N days and run follow-ups), `:booked` (simulate a booking), `:contact +91...`, `:status`, `:quit`.

## Real Telegram (untested)
`pip install aiogram`, set TELEGRAM_BOT_TOKEN (a throwaway test bot), TENANT_ACTIVATED=true, then `python -m app.main telegram`.
Real sends stay impossible while the token is a placeholder or TENANT_ACTIVATED is not true.

## Layout
`app/config` settings + client YAML validation | `app/funnel` flow engine | `app/messaging` outbound gate + gateways |
`app/ai` provider port, prompt, mock + Anthropic adapter | `app/agents` agent loop + 5 tools | `app/compliance` rules | `app/followups` scheduler | `app/knowledge` approved-FAQ lookup | `app/storage` in-memory store (Phase 1: PostgreSQL) |
`clients/clientone.yaml` all client-specific content | `tests/` unit + flow tests. See PROJECT_STATUS.md for what is and is not tested.
