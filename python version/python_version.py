import os
import time
BOT_TOKEN = "your token from @botfather"
os.environ["BOT_TOKEN"] = BOT_TOKEN
from typing import Any, Dict, Tuple

import requests
import telebot
from dotenv import load_dotenv


CHANNEL_USERNAME = "your channel if need"
CHANNEL_URL = "https://t.me/your channel if need"

ERROR_TRANSLATIONS = {
    "设备参数错误": "Invalid device parameters.",
    "参数错误": "Invalid request parameters.",
    "imei 参数错误": "Invalid IMEI.",
    "设备不存在": "Device not found.",
    "未找到设备信息": "Device information not found.",
    "系统繁忙，请稍后再试": "Xiaomi service is busy. Try again later.",
    "服务暂不可用": "Xiaomi service is temporarily unavailable.",
}


HELP_TEXT = (
    "Bot for checking Xiaomi FMI / Find Device by IMEI.\n\n"
    "To use the bot you need to subscribe to the channel @idevice_channel1.\n\n"
    "Commands:\n"
    "/help - show help\n"
    "/check <imei> - check FMI status\n\n"
    "Example:\n"
    "/check 123456789012345"
)

PENDING_IMEI_USERS = set()


def load_token() -> str:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Put it in BOT_FMI/.env")
    return token


def is_valid_imei(imei: str) -> bool:
    return imei.isdigit() and len(imei) == 15


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def translate_error_message(message: str) -> str:
    text = str(message or "").strip()
    if not text:
        return "Unknown API error."

    for source, translated in ERROR_TRANSLATIONS.items():
        if source in text:
            return translated

    return text


def fetch_fmi_status(imei: str) -> Tuple[bool, str]:
    timestamp = int(time.time() * 1000)
    url = f"https://i.mi.com/support/anonymous/status?ts={timestamp}&id={imei}"

    headers = {
        "Accept": "*/*",
        "Referer": "https://i.mi.com/find/device/activationlock",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": "uLocale=en_US; iplocale=en_US",
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException:
        return False, "An error occurred, please try again later"

    if response.status_code != 200:
        return False, "An error occurred, please try again later"

    try:
        payload: Dict[str, Any] = response.json()
    except ValueError:
        return False, "An error occurred, please try again later"

    code = payload.get("code")
    data = payload.get("data") or {}

    if code not in (0, 200):
        return False, "An error occurred, please try again later"

    locked = parse_bool(data.get("locked"))
    approved = parse_bool(data.get("approved"))
    fmi_status = "ON" if locked else "OFF"

    lines = [
        f"IMEI: {imei}",
        f"FMI: {fmi_status}",
    ]

    model = str(data.get("model") or "").strip()
    country = str(data.get("country") or "").strip()
    activated = str(data.get("activated") or "").strip()

    if model:
        lines.append(f"Model: {model}")
    if country:
        lines.append(f"Region: {country}")
    if activated:
        lines.append(f"Activated: {activated}")
    if approved:
        lines.append("Approved: YES")

    return True, "\n".join(lines)


def normalize_imei(raw_text: str) -> str:
    return "".join(ch for ch in raw_text.strip() if ch.isdigit())


def subscribe_keyboard() -> telebot.types.InlineKeyboardMarkup:
    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.add(telebot.types.InlineKeyboardButton("Subscribe", url=CHANNEL_URL))
    keyboard.add(telebot.types.InlineKeyboardButton("Check subscription", callback_data="check_subscription"))
    return keyboard


def is_user_subscribed(bot: telebot.TeleBot, user_id: int) -> tuple[bool, str]:
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
    except Exception:
        return False, "Failed to check subscription. Add bot as admin to the channel and try again."

    if member.status in {"creator", "administrator", "member"}:
        return True, ""

    return False, f"To use the bot, subscribe to the channel {CHANNEL_URL}"


def ensure_subscribed(bot: telebot.TeleBot, message: telebot.types.Message) -> bool:
    subscribed, error_text = is_user_subscribed(bot, message.from_user.id)
    if subscribed:
        return True

    PENDING_IMEI_USERS.discard(message.from_user.id)
    bot.reply_to(message, error_text, reply_markup=subscribe_keyboard())
    return False


def send_check_result(bot: telebot.TeleBot, message: telebot.types.Message, raw_imei: str) -> None:
    imei = normalize_imei(raw_imei)
    if not is_valid_imei(imei):
        bot.reply_to(message, "Send a valid 15-digit IMEI.")
        return

    wait_message = bot.reply_to(message, f"Checking IMEI {imei}...")
    ok, result_text = fetch_fmi_status(imei)
    bot.edit_message_text(
        result_text,
        chat_id=wait_message.chat.id,
        message_id=wait_message.message_id,
    )


def build_bot() -> telebot.TeleBot:
    bot = telebot.TeleBot(load_token(), parse_mode=None)

    @bot.message_handler(commands=["start", "help"])
    def handle_start(message: telebot.types.Message) -> None:
        PENDING_IMEI_USERS.discard(message.from_user.id)
        bot.reply_to(message, HELP_TEXT, reply_markup=subscribe_keyboard())

    @bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
    def handle_subscription_check(call: telebot.types.CallbackQuery) -> None:
        subscribed, error_text = is_user_subscribed(bot, call.from_user.id)
        if subscribed:
            bot.answer_callback_query(call.id, "Subscription confirmed")
            bot.send_message(call.message.chat.id, "Subscription confirmed. You can use /check")
            return

        bot.answer_callback_query(call.id, "Subscription not found")
        bot.send_message(call.message.chat.id, error_text, reply_markup=subscribe_keyboard())

    @bot.message_handler(commands=["check"])
    def handle_check(message: telebot.types.Message) -> None:
        if not ensure_subscribed(bot, message):
            return

        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            PENDING_IMEI_USERS.discard(message.from_user.id)
            send_check_result(bot, message, parts[1])
            return

        PENDING_IMEI_USERS.add(message.from_user.id)
        bot.reply_to(message, "Send me the IMEI and I will check the FMI status.")

    @bot.message_handler(func=lambda msg: msg.from_user.id in PENDING_IMEI_USERS and bool(msg.text) and not msg.text.startswith("/"))
    def handle_pending_imei(message: telebot.types.Message) -> None:
        if not ensure_subscribed(bot, message):
            return

        PENDING_IMEI_USERS.discard(message.from_user.id)
        send_check_result(bot, message, message.text)

    return bot


def main() -> None:
    bot = build_bot()
    print("BOT_FMI started")
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)


if __name__ == "__main__":
    main()
