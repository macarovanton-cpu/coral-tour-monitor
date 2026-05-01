"""Обработка команд от Telegram-бота через getUpdates."""
import os
import json
import requests
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config.json"
SUBSCRIBERS_PATH = DATA_DIR / "subscribers.json"
STATE_PATH = DATA_DIR / "state.json"

DASHBOARD_URL = "https://macarovanton-cpu.github.io/coral-tour-monitor/"

HELP_TEXT = """🤖 Coral Tour Price Monitor

<b>Подписка:</b>
/subscribe — получать уведомления
/unsubscribe — отписаться

<b>Информация:</b>
/status — текущая цена и состояние триггеров
/triggers — список триггеров
/dashboard — ссылка на график
/help — это сообщение

<b>Управление (только для админа):</b>
/enable &lt;имя_триггера&gt; — включить
/disable &lt;имя_триггера&gt; — выключить
/threshold &lt;число&gt; — порог цены
/quiet_on / /quiet_off — тихие часы
/subscribers — список подписчиков

Имена триггеров: price_below_threshold, new_absolute_minimum, sharp_drop_24h, daily_summary, quiet_hours
"""


def load_json(path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send(token, chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"send error: {e}")


def get_updates(token, offset):
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": 0},
            timeout=10,
        )
        return r.json().get("result", [])
    except Exception as e:
        print(f"getUpdates error: {e}")
        return []


def handle_command(token, admin_id, chat_id, text):
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]
    arg = parts[1] if len(parts) > 1 else ""

    is_admin = chat_id == admin_id
    subs = load_json(SUBSCRIBERS_PATH, [])
    config = load_json(CONFIG_PATH, {})

    if cmd in ("/start", "/help"):
        send(token, chat_id, HELP_TEXT)
        return

    if cmd == "/subscribe":
        if chat_id in subs:
            send(token, chat_id, "Вы уже подписаны.")
        else:
            subs.append(chat_id)
            save_json(SUBSCRIBERS_PATH, subs)
            send(token, chat_id,
                 f"✅ Подписка оформлена. Уведомлений: {len(subs)}\n"
                 f"График: {DASHBOARD_URL}")
        return

    if cmd == "/unsubscribe":
        if chat_id in subs:
            subs.remove(chat_id)
            save_json(SUBSCRIBERS_PATH, subs)
            send(token, chat_id, "Вы отписаны.")
        else:
            send(token, chat_id, "Вы не были подписаны.")
        return

    if cmd == "/dashboard":
        send(token, chat_id, f"📊 {DASHBOARD_URL}")
        return

    if cmd == "/status":
        from monitor import load_history
        hist = load_history()
        if not hist:
            send(token, chat_id, "Истории ещё нет.")
            return
        current = hist[-1]["amount"]
        all_min = min(r["amount"] for r in hist)
        triggers = config.get("triggers", {})
        lines = [f"💰 Текущая: {current:,.0f} ₽",
                 f"📉 Минимум за всё: {all_min:,.0f} ₽",
                 f"📈 Замеров: {len(hist)}",
                 "",
                 "<b>Триггеры:</b>"]
        for name, t in triggers.items():
            mark = "🟢" if t.get("enabled") else "🔴"
            lines.append(f"{mark} {name}")
        send(token, chat_id, "\n".join(lines))
        return

    if cmd == "/triggers":
        triggers = config.get("triggers", {})
        lines = ["<b>Триггеры:</b>"]
        for name, t in triggers.items():
            mark = "🟢" if t.get("enabled") else "🔴"
            extra = ""
            if name == "price_below_threshold":
                extra = f" (порог {t.get('threshold'):,} ₽)"
            elif name == "sharp_drop_24h":
                extra = f" (-{t.get('drop_rub'):,} ₽ или -{t.get('drop_percent')}%)"
            elif name == "daily_summary":
                extra = f" ({t.get('time')} МСК)"
            elif name == "quiet_hours":
                extra = f" ({t.get('start')}–{t.get('end')})"
            lines.append(f"{mark} <code>{name}</code>{extra}")
        send(token, chat_id, "\n".join(lines))
        return

    # Админские команды
    if not is_admin:
        if cmd in ("/enable", "/disable", "/threshold", "/quiet_on", "/quiet_off", "/subscribers"):
            send(token, chat_id, "⛔ Эта команда только для администратора.")
            return
        send(token, chat_id, "Неизвестная команда. /help — список команд.")
        return

    if cmd == "/enable":
        if arg in config.get("triggers", {}):
            config["triggers"][arg]["enabled"] = True
            save_json(CONFIG_PATH, config)
            send(token, chat_id, f"🟢 {arg} включён")
        else:
            send(token, chat_id, f"Триггер '{arg}' не найден.")
        return

    if cmd == "/disable":
        if arg in config.get("triggers", {}):
            config["triggers"][arg]["enabled"] = False
            save_json(CONFIG_PATH, config)
            send(token, chat_id, f"🔴 {arg} выключен")
        else:
            send(token, chat_id, f"Триггер '{arg}' не найден.")
        return

    if cmd == "/threshold":
        try:
            value = int(arg.replace(" ", "").replace(",", ""))
            config["triggers"]["price_below_threshold"]["threshold"] = value
            save_json(CONFIG_PATH, config)
            send(token, chat_id, f"Порог установлен: {value:,} ₽")
        except (ValueError, KeyError):
            send(token, chat_id, "Использование: /threshold 60000")
        return

    if cmd == "/quiet_on":
        config["triggers"]["quiet_hours"]["enabled"] = True
        save_json(CONFIG_PATH, config)
        send(token, chat_id, "🟢 Тихие часы включены")
        return

    if cmd == "/quiet_off":
        config["triggers"]["quiet_hours"]["enabled"] = False
        save_json(CONFIG_PATH, config)
        send(token, chat_id, "🔴 Тихие часы выключены")
        return

    if cmd == "/subscribers":
        send(token, chat_id, f"Подписчиков: {len(subs)}\n" + "\n".join(str(s) for s in subs))
        return

    send(token, chat_id, "Неизвестная команда. /help — список команд.")


def process_commands(token, admin_id):
    state = load_json(STATE_PATH, {"last_update_id": 0})
    offset = state.get("last_update_id", 0) + 1
    updates = get_updates(token, offset)
    if not updates:
        return
    max_id = state.get("last_update_id", 0)
    for upd in updates:
        max_id = max(max_id, upd["update_id"])
        msg = upd.get("message")
        if not msg or "text" not in msg:
            continue
        chat_id = msg["chat"]["id"]
        text = msg["text"]
        if text.startswith("/"):
            handle_command(token, admin_id, chat_id, text)
    state["last_update_id"] = max_id
    save_json(STATE_PATH, state)
