# Coral Tour Price Monitor

Мониторинг цены тура на Coral.ru каждые 15 минут с уведомлениями в Telegram и графиками.

**Бот:** [@coral_price_monitor_bot](https://t.me/coral_price_monitor_bot) — отправьте /subscribe, чтобы получать уведомления.

**Дашборд:** https://macarovanton-cpu.github.io/coral-tour-monitor/

## Триггеры
- `price_below_threshold` — цена ниже порога (по умолчанию 60 000 ₽)
- `new_absolute_minimum` — новый исторический минимум
- `sharp_drop_24h` — резкая просадка за 24 часа
- `daily_summary` — утренняя сводка в 09:00 МСК
- `quiet_hours` — тихие часы 23:00–08:00 (критичные триггеры прорываются)

## Команды бота
`/subscribe`, `/unsubscribe`, `/status`, `/triggers`, `/dashboard`, `/help`

Админские: `/enable <name>`, `/disable <name>`, `/threshold <number>`, `/quiet_on`, `/quiet_off`, `/subscribers`
