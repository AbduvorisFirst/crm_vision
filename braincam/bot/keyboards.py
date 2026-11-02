from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
)
from braincam.config import settings

def get_miniapp_url() -> str:
    return f"{settings.WEB_BASE_URL}/miniapp"

def is_https_enabled() -> bool:
    """Telegram WebApp strictly requires HTTPS. Returns True if HTTPS is configured."""
    return settings.WEB_BASE_URL.startswith("https://")

def get_onboarding_keyboard(language: str = "ru") -> ReplyKeyboardMarkup:
    """Keyboard for new/unregistered users"""
    url = get_miniapp_url()
    has_https = is_https_enabled()

    app_btn_text = "📱 Открыть Mini App" if language == "ru" else "📱 Mini App-ni ochish"
    reg_btn_text = "📝 Подключить 7 дней бесплатно" if language == "ru" else "📝 7 kunlik bepul sinovga ulanish"
    info_btn = "ℹ️ О сервисе и пользе" if language == "ru" else "ℹ️ Xizmat haqida ma'lumot"
    lang_btn = "🌐 Сменить язык" if language == "ru" else "🌐 Tilni o'zgartirish"

    first_row = []
    if has_https:
        first_row.append(KeyboardButton(text=app_btn_text, web_app=WebAppInfo(url=url)))
    first_row.append(KeyboardButton(text=reg_btn_text))

    buttons = [
        first_row,
        [KeyboardButton(text=lang_btn), KeyboardButton(text=info_btn)]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_main_keyboard(language: str = "ru", days_left: int = 7) -> ReplyKeyboardMarkup:
    """Main menu keyboard for active merchant with strictly 3 buttons"""
    url = get_miniapp_url()
    has_https = is_https_enabled()

    if language == "uz":
        btn1_text = "📊 Bugungi hisobot"
        btn2_text = "💳 Qolgan muddat va to'lov"
        btn3_text = "📱 Mini App-ga kirish"
    else:
        btn1_text = "📊 Отчет за сегодня"
        btn2_text = "💳 Сколько осталось оплата"
        btn3_text = "📱 Войти в Mini App"

    if has_https:
        btn3 = KeyboardButton(text=btn3_text, web_app=WebAppInfo(url=url))
    else:
        btn3 = KeyboardButton(text=btn3_text)

    buttons = [
        [KeyboardButton(text=btn1_text)],
        [KeyboardButton(text=btn2_text)],
        [btn3]
    ]

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_miniapp_inline_keyboard(language: str = "ru") -> InlineKeyboardMarkup:
    """Direct inline button to launch the Mini App (uses WebAppInfo if HTTPS, otherwise URL button)"""
    url = get_miniapp_url()
    has_https = is_https_enabled()
    text = "📱 Открыть BrainCam Mini App 🚀" if language == "ru" else "📱 BrainCam Mini App-ni ochish 🚀"

    if has_https:
        buttons = [
            [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]
        ]
    else:
        # If localhost HTTP, open as regular browser link
        buttons = [
            [InlineKeyboardButton(text=text, url=url)]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_approval_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Inline buttons sent to owner @abdvoris07 to approve merchant registration"""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Одобрить доступ (7 дней Trial)", callback_data=f"admin:approve:{user_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin:reject:{user_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_payment_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    """Inline buttons sent to owner @abdvoris07 to verify payment receipt"""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Подтвердить оплату (+30 дней)", callback_data=f"admin:pay_ok:{payment_id}"),
            InlineKeyboardButton(text="❌ Отклонить чек", callback_data=f"admin:pay_no:{payment_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_language_inline_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang:uz")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_report_time_inline_keyboard() -> InlineKeyboardMarkup:
    """Quick selection for daily report hour"""
    buttons = [
        [
            InlineKeyboardButton(text="19:00", callback_data="time:19:00"),
            InlineKeyboardButton(text="20:00", callback_data="time:20:00"),
            InlineKeyboardButton(text="21:00", callback_data="time:21:00")
        ],
        [
            InlineKeyboardButton(text="22:00", callback_data="time:22:00"),
            InlineKeyboardButton(text="23:00", callback_data="time:23:00"),
            InlineKeyboardButton(text="00:00", callback_data="time:00:00")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_camera_actions_inline(camera_id: int, language: str = "ru") -> InlineKeyboardMarkup:
    if language == "uz":
        buttons = [
            [
                InlineKeyboardButton(text="📸 Kadr olish", callback_data=f"cam:snap:{camera_id}"),
                InlineKeyboardButton(text="⚡️ AI Tahlil", callback_data=f"cam:analyze:{camera_id}")
            ],
            [
                InlineKeyboardButton(text="🔄 Ulanishni tekshirish", callback_data=f"cam:test:{camera_id}")
            ]
        ]
    else:
        buttons = [
            [
                InlineKeyboardButton(text="📸 Снимок с камеры", callback_data=f"cam:snap:{camera_id}"),
                InlineKeyboardButton(text="⚡️ AI Анализ", callback_data=f"cam:analyze:{camera_id}")
            ],
            [
                InlineKeyboardButton(text="🔄 Проверить связь", callback_data=f"cam:test:{camera_id}")
            ]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_camera_guide_keyboard(language: str = "ru") -> InlineKeyboardMarkup:
    """Button to open camera integration instructions"""
    text = "📖 Инструкция по подключению камер" if language == "ru" else "📖 Kameralarni ulash bo'yicha qo'llanma"
    url = get_miniapp_url()
    has_https = is_https_enabled()

    if language == "uz":
        app_btn_text = "📱 Mini App-da ochish" if has_https else "📱 Brauzerda ochish"
    else:
        app_btn_text = "📱 Открыть в Mini App" if has_https else "📱 Открыть в браузере"

    if has_https:
        app_btn = InlineKeyboardButton(text=app_btn_text, web_app=WebAppInfo(url=url))
    else:
        app_btn = InlineKeyboardButton(text=app_btn_text, url=url)

    buttons = [
        [InlineKeyboardButton(text=text, callback_data="cam:guide")],
        [app_btn]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_settings_inline_keyboard(language: str = "ru") -> InlineKeyboardMarkup:
    """Settings menu inline buttons"""
    url = get_miniapp_url()
    has_https = is_https_enabled()

    if language == "uz":
        buttons = [
            [
                InlineKeyboardButton(text="🌐 Tilni o'zgartirish", callback_data="settings:lang"),
                InlineKeyboardButton(text="⏰ Hisobot vaqti", callback_data="settings:time")
            ]
        ]
        app_btn_text = "📱 Mini App-ni ochish"
    else:
        buttons = [
            [
                InlineKeyboardButton(text="🌐 Сменить язык", callback_data="settings:lang"),
                InlineKeyboardButton(text="⏰ Время отчета", callback_data="settings:time")
            ]
        ]
        app_btn_text = "📱 Открыть Mini App"

    if has_https:
        buttons.append([InlineKeyboardButton(text=app_btn_text, web_app=WebAppInfo(url=url))])
    else:
        buttons.append([InlineKeyboardButton(text=app_btn_text, url=url)])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
