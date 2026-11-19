# Client setup checklist (clients/clientone.yaml + .env)

Run `python -m app.main check-config` any time: it lists exactly what is still missing.

## Accounts and credentials (client owns these - put in .env, never in YAML)
- [ ] Telegram bot created via @BotFather: TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME
- [ ] Sales team Telegram chat id: SALES_NOTIFICATION_CHAT_ID
- [ ] Booking link (Cal.com or Calendly): BOOKING_URL
- [ ] LLM provider account owned by the client: LLM_PROVIDER=anthropic, LLM_API_KEY, LLM_MODEL (model id from provider docs)
- [ ] Free guide PDF file: FREE_GUIDE_PATH
- [ ] Production database (Phase 1): DATABASE_URL

## Content (fill in clients/clientone.yaml)
- [ ] client.name, business_description, target_audience
- [ ] client.privacy_notice: approved text (what data, why, retention, who sees it, how to opt out)
- [ ] Free guide title (lead_magnets)
- [ ] FAQ answers: fee, duration, curriculum (and any more); only approved facts
- [ ] Approval of the message wording in `messages:` and the day 1/3/7 follow-up texts
- [ ] Qualification questions the sales team wants answered
- [ ] Reel deep-link campaign names (e.g. t.me/<bot>?start=reel_launch1)

## Decisions and approvals
- [ ] Phone collected before questions (as in diagram) or at the guide step
- [ ] How the sales team calls: booked slot only, or any "yes"
- [ ] Review by a qualified Indian securities-law professional of the rules, messages, disclaimers and marketing claims
- [ ] Consent for being phoned and for data storage confirmed by counsel (telecom/data-protection obligations are for counsel to advise)
- [ ] Approval of llm.allow_general_education (may the AI explain general market concepts beyond the approved FAQ?)
- [ ] Statement on regulatory registration status the bot may or may not make (default: it makes none)
- [ ] Then set compliance.legal_review_completed: true, TENANT_ACTIVATED=true, FOLLOWUPS_ENABLED=true
