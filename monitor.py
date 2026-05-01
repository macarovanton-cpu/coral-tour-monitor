"""Парсит цену тура с coral.ru и пишет в data/prices.csv."""
import os
import re
import json
import csv
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

URL = "https://www.coral.ru/hotels/turkey/club-side-coast-hotel-side/?qp=gEIDPqjHDS6F9wLPRxSMEkpW5JZgU302duAHvtg4%2fuuXJ0cmzOJPLNfWG01BtAhZKuKXfwTW6nHNqCf7gqN1EYOLo7DrD3HgDle3W8dHzBeu4w35LYynhnEmzOMjX6DbCMnfJODOaig3KBpVqbL3NbBqyS2%2bJJLLjV4qavCWVNJHybbvqwCmw4N9x171vjoIC%2b6xEYU45bFoU%2bapP7tiYsTMEL0x3o8WZV8zsGhwoXmggW%2bSnGKTjyGHqm0gMia0Ms089gpq6uEYfJQOuR9Xs%2fck0RLFNGpqlm%2f8%2bx3Btv1vr0yxdsQvwSUnT4B4C8UOTaQLQQ0ZozagqJNKRlTiJsr6DUXT05I16ugVCTTVn6a2KgQexazqlgYFzRbqpAoHNTVlVfX9FUw72X9X2Ue8aarkVWFS3Q%2fDS%2f25HPhIbTznGCJiZW5oiv9O9s3OKMQrDKbqcjady%2bOlRt0f3ZiJGdKtd6PFvbFe0VA4j4ghbpZZkWKI8kvfX0WjclSb6T8QX8mHnHNIiAkip9m5BQweJg%3d%3d&p=1&w=0&s=5&hlu=packagetours/sochi-to-turtsiya-tours/"

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CSV_PATH = DATA_DIR / "prices.csv"
CONFIG_PATH = ROOT / "config.json"
SUBSCRIBERS_PATH = DATA_DIR / "subscribers.json"
STATE_PATH = DATA_DIR / "state.json"  # last_update_id для getUpdates

MSK = timezone(timedelta(hours=3))


def find_key_recursive(obj, key):
    """Рекурсивно ищет первое вхождение ключа в JSON."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key_recursive(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = find_key_recursive(item, key)
            if r is not None:
                return r
    return None


def fetch_price():
    """Возвращает (min_price, currency, room_name, meal_type) или None при ошибке."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    r = requests.get(URL, headers=headers, timeout=30)
    r.raise_for_status()
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        r.text, re.S
    )
    if not m:
        raise RuntimeError("__NEXT_DATA__ не найден в HTML")
    data = json.loads(m.group(1))
    response = (find_key_recursive(data, "packageTourPriceSearchResponse")
                or find_key_recursive(data, "onlyHotelPriceSearchResponse"))
    if not response:
        raise RuntimeError("priceSearchResponse не найден в __NEXT_DATA__")
    products = response.get("products", [])
    if not products:
        raise RuntimeError("products пуст")
    cheapest = min(products, key=lambda p: p["price"]["amount"])
    return {
        "amount": cheapest["price"]["amount"],
        "currency": cheapest["price"]["currency"],
        "room": cheapest.get("rooms", [{}])[0].get("name", ""),
        "meal": cheapest.get("rooms", [{}])[0].get("mealType", {}).get("name", ""),
        "raw": cheapest,
    }


def append_price_to_csv(price_data):
    DATA_DIR.mkdir(exist_ok=True)
    is_new = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["timestamp_msk", "amount", "currency", "room", "meal"])
        w.writerow([
            datetime.now(MSK).isoformat(),
            price_data["amount"],
            price_data["currency"],
            price_data["room"],
            price_data["meal"],
        ])


def load_history():
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["amount"] = float(row["amount"])
        row["timestamp_msk"] = datetime.fromisoformat(row["timestamp_msk"])
    return rows


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_subscribers():
    if not SUBSCRIBERS_PATH.exists():
        return []
    with open(SUBSCRIBERS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_subscribers(subs):
    DATA_DIR.mkdir(exist_ok=True)
    with open(SUBSCRIBERS_PATH, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)


def load_state():
    if not STATE_PATH.exists():
        return {"last_update_id": 0}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    DATA_DIR.mkdir(exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_quiet_hours(config):
    """Тихие часы по МСК."""
    if not config["triggers"].get("quiet_hours", {}).get("enabled"):
        return False
    qh = config["triggers"]["quiet_hours"]
    now = datetime.now(MSK).time()
    start = datetime.strptime(qh["start"], "%H:%M").time()
    end = datetime.strptime(qh["end"], "%H:%M").time()
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def check_triggers(price_data, history, config):
    """Возвращает список (trigger_name, message, is_critical)."""
    alerts = []
    current = price_data["amount"]
    triggers = config["triggers"]

    # 1. Цена ниже порога — критичная, прорывается через тихие часы
    t = triggers.get("price_below_threshold", {})
    if t.get("enabled"):
        thr = t.get("threshold", 60000)
        if current <= thr:
            alerts.append((
                "price_below_threshold",
                f"🔥 ЦЕНА УПАЛА НИЖЕ ПОРОГА!\n\n"
                f"Текущая: {current:,.0f} ₽ ≤ {thr:,.0f} ₽\n"
                f"Номер: {price_data['room']}\n"
                f"Питание: {price_data['meal']}",
                True,
            ))

    # 2. Новый абсолютный минимум
    t = triggers.get("new_absolute_minimum", {})
    if t.get("enabled") and len(history) > 1:
        prev_min = min(r["amount"] for r in history[:-1])
        if current < prev_min:
            alerts.append((
                "new_absolute_minimum",
                f"📉 Новый абсолютный минимум\n\n"
                f"Было: {prev_min:,.0f} ₽\n"
                f"Стало: {current:,.0f} ₽\n"
                f"Δ: -{prev_min - current:,.0f} ₽",
                False,
            ))

    # 3. Резкая просадка за 24 часа
    t = triggers.get("sharp_drop_24h", {})
    if t.get("enabled") and history:
        cutoff = datetime.now(MSK) - timedelta(hours=24)
        day_ago = [r for r in history if r["timestamp_msk"] >= cutoff]
        if len(day_ago) >= 2:
            ref = day_ago[0]["amount"]
            drop_rub = ref - current
            drop_pct = (drop_rub / ref * 100) if ref else 0
            if drop_rub >= t.get("drop_rub", 5000) or drop_pct >= t.get("drop_percent", 7):
                alerts.append((
                    "sharp_drop_24h",
                    f"⬇️ Резкая просадка за 24ч\n\n"
                    f"24ч назад: {ref:,.0f} ₽\n"
                    f"Сейчас: {current:,.0f} ₽\n"
                    f"Δ: -{drop_rub:,.0f} ₽ ({drop_pct:.1f}%)",
                    False,
                ))

    return alerts


def maybe_send_daily_summary(history, config, send_fn):
    """Утренняя сводка в config.triggers.daily_summary.time МСК."""
    t = config["triggers"].get("daily_summary", {})
    if not t.get("enabled"):
        return
    target = datetime.strptime(t.get("time", "09:00"), "%H:%M").time()
    now = datetime.now(MSK)
    # окно срабатывания — от target до target+30мин (чтобы поймать любой запуск в этот период)
    target_dt = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    if not (target_dt <= now < target_dt + timedelta(minutes=30)):
        return
    # проверяем, не отправили ли уже сегодня
    state = load_state()
    last_sent = state.get("last_summary_date")
    today = now.date().isoformat()
    if last_sent == today:
        return
    if not history:
        return
    current = history[-1]["amount"]
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    day = [r["amount"] for r in history if r["timestamp_msk"] >= cutoff_24h]
    week = [r["amount"] for r in history if r["timestamp_msk"] >= cutoff_7d]
    msg = (
        f"☀️ Утренняя сводка\n\n"
        f"Текущая цена: {current:,.0f} ₽\n"
        f"Минимум за сутки: {min(day):,.0f} ₽\n"
        f"Максимум за сутки: {max(day):,.0f} ₽\n"
        f"Средняя за неделю: {sum(week)/len(week):,.0f} ₽\n"
        f"Минимум за неделю: {min(week):,.0f} ₽"
    )
    send_fn(msg)
    state["last_summary_date"] = today
    save_state(state)


def telegram_send(token, chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"Telegram send error to {chat_id}: {e}", file=sys.stderr)


def broadcast(token, subscribers, text):
    for chat_id in subscribers:
        telegram_send(token, chat_id, text)


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    admin_id = int(os.environ["ADMIN_CHAT_ID"])

    # 1. Обработка команд бота
    from bot_commands import process_commands
    process_commands(token, admin_id)

    # 2. Получение цены
    try:
        price_data = fetch_price()
    except Exception as e:
        # шлём только админу при ошибке парсинга
        telegram_send(
            token, admin_id,
            f"⚠️ Ошибка мониторинга\n\n{type(e).__name__}: {e}"
        )
        raise

    append_price_to_csv(price_data)

    # 3. Триггеры
    history = load_history()
    config = load_config()
    subscribers = load_subscribers()
    quiet = is_quiet_hours(config)
    alerts = check_triggers(price_data, history, config)

    for trigger_name, message, is_critical in alerts:
        if quiet and not is_critical:
            continue  # копится до утра, но не отправляется
        broadcast(token, subscribers, message)

    # 4. Утренняя сводка
    maybe_send_daily_summary(
        history, config,
        lambda msg: broadcast(token, subscribers, msg)
    )

    print(f"OK: {price_data['amount']} {price_data['currency']} | "
          f"{price_data['room']} | {price_data['meal']}")


if __name__ == "__main__":
    main()
