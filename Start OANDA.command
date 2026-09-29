#!/bin/zsh
set -eu
cd -- "${0:A:h}"
export OANDA_ENVIRONMENT=practice
export DASHBOARD_HOST=127.0.0.1
export MT4_ENABLED=false
export SHEETS_SYNC_ENABLED=false
export SLACK_BOT_TOKEN=''
export SLACK_WEBHOOK_URL=''
exec .venv/bin/python -m src.main
