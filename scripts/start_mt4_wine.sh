#!/usr/bin/env bash
# Headless MetaTrader 4 on this Linux box (Wine + Xvfb).
# Logs into the same MetaQuotes demo as the laptop terminal so desk
# copies appear on both. Secrets come from .env — nothing is committed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
set -a
[ -f "$ROOT/.env" ] && . "$ROOT/.env"
set +a

export DISPLAY="${DISPLAY:-:44}"
export WINEPREFIX="${WINEPREFIX:-$ROOT/data/mt4-prefix64}"
export WINEARCH="${WINEARCH:-win64}"
export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-mscoree,mshtml=}"

MT4="$WINEPREFIX/drive_c/Program Files (x86)/MetaTrader 4"
HUB_PORT="${HUB_PORT:-8765}"
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
HUB_URL="${MT4_HUB_URL:-http://${HOST_IP:-127.0.0.1}:${HUB_PORT}}"
SECRET="${MT4_BRIDGE_SECRET:-}"
LOGIN="${MT4_LOGIN:-}"
PASSWORD="${MT4_PASSWORD:-}"
SERVER="${MT4_SERVER:-MetaQuotes-Demo}"

if [ ! -x "$MT4/terminal.exe" ]; then
  echo "MT4 is not installed in $MT4" >&2
  exit 1
fi

mkdir -p "$MT4/MQL4/Experts" "$MT4/MQL4/Presets" "$MT4/profiles/Sentinel" "$MT4/config"
cp -f "$ROOT/mt4/ForexSentinelBridge.mq4" "$MT4/MQL4/Experts/ForexSentinelBridge.mq4"

{
  printf 'HubUrl=%s\r\n' "$HUB_URL"
  printf 'BridgeSecret=%s\r\n' "$SECRET"
  printf 'Magic=212100\r\n'
  printf 'PollSeconds=5\r\n'
  printf 'TradeSymbol=EURUSD\r\n'
} > "$MT4/MQL4/Presets/ForexSentinelBridge.set"

python3 - "$MT4" "$HUB_URL" "$SECRET" "$LOGIN" "$PASSWORD" "$SERVER" <<'PY'
import sys, struct
from pathlib import Path
mt4, hub, secret, login, password, server = sys.argv[1:]
base = Path(mt4)

chr_text = f"""<chart>
symbol=EURUSD
period=5
leftpos=1
digits=5
scale=8
graph=1
fore=1
grid=1
volume=0
scroll=1
shift=1
ohlc=1
one_click=0
askline=1
days=0
descriptions=0
shift_size=20
fixed_pos=0
window_left=0
window_top=0
window_right=1200
window_bottom=600
window_type=3
background_color=0
foreground_color=16777215
barup_color=65280
bardown_color=255
bullcandle_color=0
bearcandle_color=16777215
chartline_color=65280
volumes_color=3329330
grid_color=10061943
askline_color=255
stops_color=255

<window>
height=100
<indicator>
name=main
</indicator>
</window>

<expert>
name=ForexSentinelBridge
flags=343
window_num=0
<inputs>
HubUrl={hub}
BridgeSecret={secret}
Magic=212100
PollSeconds=5
TradeSymbol=EURUSD
</inputs>
</expert>
</chart>
""".replace("\n", "\r\n")
(base / "profiles/Sentinel").mkdir(parents=True, exist_ok=True)
(base / "profiles/Sentinel/chart01.CHR").write_bytes(chr_text.encode("ascii"))
(base / "templates/ForexSentinelBridge.tpl").write_bytes(chr_text.encode("ascii"))
(base / "profiles/lastprofile.ini").write_bytes(b"Sentinel\r\n")

ini = f"""Login={login}
Password={password}
Server={server}
Profile=Sentinel
ExpertsEnable=true
ExpertsDllImport=false
ExpertsExpImport=true
ExpertsTrades=true
Symbol=EURUSD
Period=5
Template=ForexSentinelBridge.tpl
Expert=ForexSentinelBridge
ExpertParameters=ForexSentinelBridge.set
""".replace("\n", "\r\n")
(base / "start.ini").write_bytes(ini.encode("ascii"))
(base / "config/start.ini").write_bytes(ini.encode("ascii"))

experts = base / "config/experts.ini"
data = bytearray(experts.read_bytes()) if experts.exists() else bytearray(4388)
if len(data) < 4388:
    data.extend(b"\x00" * (4388 - len(data)))
# Allow automated trading + WebRequest flags (see experts.ini DWORD map).
struct.pack_into("<I", data, 0, 400)
struct.pack_into("<I", data, 4, 1)
struct.pack_into("<I", data, 8, 1)
struct.pack_into("<I", data, 12, 1)
struct.pack_into("<I", data, 24, 1)
struct.pack_into("<I", data, 28, 1)
struct.pack_into("<I", data, 36, 1)
urls = [
    hub,
    "http://127.0.0.1:8765",
    "http://localhost:8765",
]
seen = []
for u in urls:
    if u and u not in seen:
        seen.append(u)
struct.pack_into("<I", data, 48, len(seen))
slot = 256
base_off = 292
for i, u in enumerate(seen[:16]):
    raw = u.encode("utf-16-le") + b"\x00\x00"
    off = base_off + i * slot
    data[off:off + slot] = b"\x00" * slot
    data[off:off + min(len(raw), slot)] = raw[:slot]
experts.write_bytes(data)
print("hub", hub, "urls", seen)
PY

if ! pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 1280x800x24 -ac +extension GLX >/tmp/xvfb44.log 2>&1 &
  sleep 1
  fluxbox >/tmp/fluxbox44.log 2>&1 &
  sleep 1
fi

cd "$MT4"
if [ ! -f "$MT4/MQL4/Experts/ForexSentinelBridge.ex4" ] || [ "$MT4/MQL4/Experts/ForexSentinelBridge.mq4" -nt "$MT4/MQL4/Experts/ForexSentinelBridge.ex4" ]; then
  wine metaeditor.exe /compile:"MQL4\\Experts\\ForexSentinelBridge.mq4" >/tmp/mt4-compile.log 2>&1 || true
fi

exec wine terminal.exe start.ini
