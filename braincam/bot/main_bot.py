import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, MenuButtonWebApp, WebAppInfo
from sqlalchemy import select

from braincam.config import settings
from braincam.db.session import async_session, init_db
from braincam.db.models import (
    Organization, User, Camera, DailyReport, PaymentReceipt,
    UserStatusEnum, EventTypeEnum
)
from braincam.bot.keyboards import (
    get_onboarding_keyboard, get_main_keyboard, get_admin_approval_keyboard,
    get_admin_payment_keyboard, get_language_inline_keyboard,
    get_report_time_inline_keyboard, get_camera_actions_inline,
    get_camera_guide_keyboard, get_miniapp_inline_keyboard, get_miniapp_url,
    get_settings_inline_keyboard
)
from braincam.ai.gemini_service import gemini_service
from braincam.video.rtsp_capture import RTSPCaptureService
from braincam.services.analytics_service import AnalyticsService
from braincam.services.notification_service import NotificationService

logger = logging.getLogger("braincam.bot")
dp = Dispatcher()

# FSM States
class RegistrationStates(StatesGroup):
    full_name = State()
    phone = State()
    store_name = State()
    business_category = State()
    city = State()
    instagram = State()
    camera_count = State()

class PaymentStates(StatesGroup):
    waiting_receipt = State()

class CustomReportTimeStates(StatesGroup):
    waiting_time = State()

# Helpers
async def get_user_and_org(session, telegram_user: types.User) -> tuple[Optional[User], Optional[Organization]]:
    stmt = select(User).where(User.telegram_id == telegram_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    org = None
    if user and user.org_id:
        org_stmt = select(Organization).where(Organization.id == user.org_id)
        org_res = await session.execute(org_stmt)
        org = org_res.scalar_one_or_none()
    return user, org

async def notify_admin(bot: Bot, text: str, reply_markup=None, photo_file_id=None):
    """Sends notification to owner @abdvoris07"""
    # 1. If admin Telegram ID is known, send directly
    admin_id = settings.ADMIN_TELEGRAM_ID
    if not admin_id:
        # Check if user with username @abdvoris07 has interacted with the bot
        async with async_session() as session:
            stmt = select(User).where(User.username == settings.ADMIN_TELEGRAM_USERNAME)
            res = await session.execute(stmt)
            admin_user = res.scalar_one_or_none()
            if admin_user:
                admin_id = admin_user.telegram_id

    if admin_id:
        try:
            if photo_file_id:
                await bot.send_photo(chat_id=admin_id, photo=photo_file_id, caption=text, reply_markup=reply_markup, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=admin_id, text=text, reply_markup=reply_markup, parse_mode="HTML")
            return
        except Exception as e:
            logger.warning(f"Failed to send direct notification to admin {admin_id}: {e}")

    logger.info(f"[ADMIN NOTIFICATION FOR @{settings.ADMIN_TELEGRAM_USERNAME}]:\n{text}")

# ================= COMMAND /start =================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    """Handler for /start command with interactive onboarding & value proposition"""
    await state.clear()

    # Set persistent Mini App menu button next to input field if HTTPS is enabled
    url = get_miniapp_url()
    if url.startswith("https://"):
        try:
            await bot.set_chat_menu_button(
                chat_id=message.chat.id,
                menu_button=MenuButtonWebApp(
                    text="📱 BrainCam App",
                    web_app=WebAppInfo(url=url)
                )
            )
        except Exception as e:
            logger.debug(f"Menu button set skipped: {e}")

    async with async_session() as session:
        user, org = await get_user_and_org(session, message.from_user)

        # Automatically remember admin if @abdvoris07 messages
        if message.from_user.username == settings.ADMIN_TELEGRAM_USERNAME:
            if user:
                user.role = "admin"
                user.status = UserStatusEnum.ACTIVE.value
                await session.commit()

        lang = user.language if user else "ru"

    # 1. New / Unregistered user
    if not user or user.status == UserStatusEnum.PENDING.value and not user.store_name:
        if lang == "uz":
            text = (
                f"Assalomu alaykum, <b>{message.from_user.first_name}</b>!\n\n"
                f"🚀 <b>BrainCam AI</b> — do'kon va savdo nuqtalari uchun aqlli video va audio tahlil tizimi!\n\n"
                f"<b>Biz kimmiz va qanday yordam beramiz:</b>\n"
                f"• Mavjud oddiy IP-kameralaringizni sun'iy intellektga ulaymiz.\n"
                f"• 👥 <b>Mijozlar oqimi:</b> Kuniga qancha odam kirdi va qancha xarid bo'ldi (Konversiya %).\n"
                f"• 👔 <b>Xodimlar nazorati:</b> Xodimlar ish joyidami yoki telefonga chalg'iganmi.\n"
                f"• 🎙 <b>Ovozli tahlil:</b> Mikrofon orqali mijozlarning e'tiroz va shikoyatlarini aniqlash.\n"
                f"• 💡 <b>AI Maslahatlar:</b> Savdoni oshirish bo'yicha har kuni tavsiyalar.\n\n"
                f"🎁 <b>Barcha yangi mijozlar uchun 7 kunlik to'liq bepul sinov davri!</b>\n"
                f"Quyidagi Mini App tugmasini bosing:"
            )
        else:
            text = (
                f"Здравствуйте, <b>{message.from_user.first_name}</b>!\n\n"
                f"🚀 Добро пожаловать в <b>BrainCam AI</b>!\n"
                f"<i>«Делаем каждую камеру интеллектуальной»</i>\n\n"
                f"<b>Кто мы и какую пользу приносим вашему бизнесу:</b>\n"
                f"• Вам не нужно покупать дорогие умные камеры — мы подключаемся к вашим обычным камерам.\n"
                f"• 👥 <b>Точный трафик:</b> Сколько человек зашло в магазин и сколько реально купило (Конверсия %).\n"
                f"• 👔 <b>Контроль персонала:</b> На месте ли сотрудники, скорость обслуживания, нет ли зависания в телефонах.\n"
                f"• 🎙 <b>Аудиоконтроль:</b> Детекция жалоб клиентов и конфликтов через микрофон камеры.\n"
                f"• 💡 <b>AI-рекомендации:</b> Советы по выкладке, кассам и персоналу для роста вашей прибыли.\n\n"
                f"🎁 <b>Для всех новых клиентов: 7 дней бесплатного тест-драйва со всеми функциями!</b>\n"
                f"Откройте удобное Mini App прямо в смартфоне:"
            )
        app_prompt = "👇 Ilovani ochish uchun bosing:" if lang == "uz" else "👇 Нажмите для открытия приложения:"
        await message.answer(text, parse_mode="HTML", reply_markup=get_onboarding_keyboard(lang))
        await message.answer(app_prompt, reply_markup=get_miniapp_inline_keyboard(lang))
        return

    # 2. Waiting for Admin Approval
    if user.status == UserStatusEnum.PENDING.value:
        if lang == "uz":
            text = (
                f"⏳ <b>Arizangiz qabul qilindi va ko'rib chiqilmoqda!</b>\n\n"
                f"Administrator (@{settings.ADMIN_TELEGRAM_USERNAME}) arizangizni tasdiqlashi bilan "
                f"sizga 7 kunlik bepul sinov davri faollashadi va xabar yuboriladi."
            )
        else:
            text = (
                f"⏳ <b>Ваша заявка принята и находится на рассмотрении!</b>\n\n"
                f"Владелец сервиса (@{settings.ADMIN_TELEGRAM_USERNAME}) проверяет данные. "
                f"Как только доступ будет одобрен, вам придет уведомление и откроется Dashboard!"
            )
        await message.answer(text, parse_mode="HTML")
        return

    # 3. Active User (Approved Trial or Paid)
    days = user.days_left()
    if lang == "uz":
        text = (
            f"Assalomu alaykum, <b>{user.full_name or message.from_user.first_name}</b>!\n"
            f"🏬 Do'kon: <b>{user.store_name or 'BrainCam Store'}</b>\n"
            f"⏳ Kirish muddati: <b>{days} kun qoldi</b>\n\n"
            f"Kerakli bo'limni tanlang:"
        )
    else:
        text = (
            f"Здравствуйте, <b>{user.full_name or message.from_user.first_name}</b>!\n"
            f"🏬 Магазин: <b>{user.store_name or 'BrainCam Store'}</b>\n"
            f"⏳ Доступ активен: <b>осталось {days} дн.</b>\n\n"
            f"Выберите нужный раздел в меню:"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard(lang, days_left=days))

# ================= REGISTRATION FLOW (FSM) =================

@dp.message(F.text.in_([
    "📝 Подключить 7 дней бесплатно", "📝 7 kunlik bepul sinovga ulanish",
    "📝 Заполнить заявку в чате", "📝 Arizani chatda to'ldirish",
    "/register"
]))
async def start_registration(message: types.Message, state: FSMContext):
    """Starts step-by-step merchant registration form"""
    async with async_session() as session:
        user, _ = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"

    if message.text in ["📝 7 kunlik bepul sinovga ulanish", "📝 Arizani chatda to'ldirish"]:
        lang = "uz"

    await state.update_data(lang=lang)
    await state.set_state(RegistrationStates.full_name)
    step_title = "📝 <b>1/7-qadam</b>" if lang == "uz" else "📝 <b>Шаг 1/7</b>"
    prompt = "Ism va Familiyangizni kiriting:" if lang == "uz" else "Введите ваше Имя и Фамилию (ФИО):"
    await message.answer(f"{step_title}\n{prompt}", parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())

@dp.message(RegistrationStates.full_name)
async def reg_full_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.set_state(RegistrationStates.phone)
    step_title = "📝 <b>2/7-qadam</b>" if lang == "uz" else "📝 <b>Шаг 2/7</b>"
    prompt = "Bog'lanish uchun telefon raqamingizni kiriting (masalan: <code>+998901234567</code>):" if lang == "uz" else "Введите ваш контактный номер телефона (например: <code>+998901234567</code>):"
    await message.answer(f"{step_title}\n{prompt}", parse_mode="HTML")

@dp.message(RegistrationStates.phone)
async def reg_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.set_state(RegistrationStates.store_name)
    step_title = "📝 <b>3/7-qadam</b>" if lang == "uz" else "📝 <b>Шаг 3/7</b>"
    prompt = "Do'koningiz yoki muassasangiz nomini kiriting (masalan: <i>Baraka Supermarketi</i>):" if lang == "uz" else "Введите название вашего магазина или заведения (например: <i>Супермаркет Baraka</i>):"
    await message.answer(f"{step_title}\n{prompt}", parse_mode="HTML")

@dp.message(RegistrationStates.store_name)
async def reg_store_name(message: types.Message, state: FSMContext):
    await state.update_data(store_name=message.text.strip())
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.set_state(RegistrationStates.business_category)
    step_title = "📝 <b>4/7-qadam</b>" if lang == "uz" else "📝 <b>Шаг 4/7</b>"
    prompt = "Biznesingiz qaysi sohaga tegishli? (Oziq-ovqat/Supermarket, Kiyim-kechak, Kafe/Restoran, Dorixona, Elektronika va h.k.):" if lang == "uz" else "Какая у вас сфера бизнеса? (Продукты/Супермаркет, Одежда, Кафе/Ресторан, Аптека, Электроника и т.д.):"
    await message.answer(f"{step_title}\n{prompt}", parse_mode="HTML")

@dp.message(RegistrationStates.business_category)
async def reg_category(message: types.Message, state: FSMContext):
    await state.update_data(business_category=message.text.strip())
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.set_state(RegistrationStates.city)
    step_title = "📝 <b>5/7-qadam</b>" if lang == "uz" else "📝 <b>Шаг 5/7</b>"
    prompt = "Do'koningiz qaysi shahar va tumanda joylashgan? (masalan: <i>Toshkent, Chilonzor</i>):" if lang == "uz" else "В каком городе и районе находится ваш магазин? (например: <i>Ташкент, Чиланзар</i>):"
    await message.answer(f"{step_title}\n{prompt}", parse_mode="HTML")

@dp.message(RegistrationStates.city)
async def reg_city(message: types.Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.set_state(RegistrationStates.instagram)
    step_title = "📝 <b>6/7-qadam</b>" if lang == "uz" else "📝 <b>Шаг 6/7</b>"
    prompt = "Biznesingizning <b>Instagram sahifasi</b>ni kiriting (masalan: <code>@baraka_market</code> yoki havola):" if lang == "uz" else "Укажите <b>Instagram-аккаунт вашего бизнеса</b> (например: <code>@baraka_market</code> или ссылка):"
    await message.answer(f"{step_title}\n{prompt}", parse_mode="HTML")

@dp.message(RegistrationStates.instagram)
async def reg_instagram(message: types.Message, state: FSMContext):
    await state.update_data(instagram=message.text.strip())
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.set_state(RegistrationStates.camera_count)
    step_title = "📝 <b>7/7-qadam</b>" if lang == "uz" else "📝 <b>Шаг 7/7</b>"
    prompt = "Do'koningizda hozirda nechta kamera o'rnatilgan? (masalan: <i>2</i> yoki <i>4</i>):" if lang == "uz" else "Сколько камер у вас сейчас установлено в магазине? (например: <i>2</i> или <i>4</i>):"
    await message.answer(f"{step_title}\n{prompt}", parse_mode="HTML")

@dp.message(RegistrationStates.camera_count)
async def reg_camera_count(message: types.Message, state: FSMContext, bot: Bot):
    try:
        count = int("".join(c for c in message.text if c.isdigit()) or 1)
    except Exception:
        count = 1

    await state.update_data(camera_count=count)
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.clear()

    # Save to database with status PENDING
    async with async_session() as session:
        user, org = await get_user_and_org(session, message.from_user)
        if not org:
            org = Organization(name=data["store_name"], language=lang)
            session.add(org)
            await session.flush()
        else:
            org.language = lang

        if not user:
            user = User(
                org_id=org.id,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                language=lang
            )
            session.add(user)

        user.full_name = data["full_name"]
        user.phone = data["phone"]
        user.store_name = data["store_name"]
        user.business_category = data["business_category"]
        user.city = data["city"]
        user.instagram = data["instagram"]
        user.camera_count = count
        user.language = lang
        user.status = UserStatusEnum.PENDING.value

        await session.commit()
        await session.refresh(user)
        user_db_id = user.id

    # 1. Inform merchant
    if lang == "uz":
        confirm_text = (
            "✅ <b>Arizangiz muvaffaqiyatli yuborildi!</b>\n\n"
            f"Barcha ma'lumotlar loyiha rahbari (@{settings.ADMIN_TELEGRAM_USERNAME})ga yetkazildi.\n"
            "Tasdiqlangandan so'ng, shaxsiy kabinet va 7 kunlik bepul sinov davri avtomatik tarzda ochiladi!"
        )
    else:
        confirm_text = (
            "✅ <b>Заявка успешно отправлена!</b>\n\n"
            f"Вся информация передана владельцу проекта (@{settings.ADMIN_TELEGRAM_USERNAME}).\n"
            "После одобрения вам автоматически откроется доступ к личному кабинету и 7-дневному бесплатному периоду!"
        )
    await message.answer(confirm_text, parse_mode="HTML")

    # 2. NOTIFY ADMIN (@abdvoris07)
    admin_text = (
        f"🔔 <b>НОВАЯ ЗАЯВКА НА ПОДКЛЮЧЕНИЕ BRAINCAM AI!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>ФИО:</b> {data['full_name']}\n"
        f"📞 <b>Телефон:</b> {data['phone']}\n"
        f"🏬 <b>Магазин:</b> {data['store_name']}\n"
        f"🏷 <b>Категория:</b> {data['business_category']}\n"
        f"📍 <b>Локация:</b> {data['city']}\n"
        f"📸 <b>Instagram:</b> {data['instagram']}\n"
        f"📹 <b>Камер в наличии:</b> {count} шт.\n"
        f"💬 <b>Telegram:</b> @{message.from_user.username or 'без_юзернейма'} (ID: <code>{message.from_user.id}</code>)\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Нажмите кнопку ниже для одобрения или отклонения:"
    )
    await notify_admin(bot, admin_text, reply_markup=get_admin_approval_keyboard(user_db_id))

# ================= ADMIN CALLBACKS =================

@dp.callback_query(F.data.startswith("admin:approve:"))
async def admin_approve_merchant(callback: types.CallbackQuery, bot: Bot):
    user_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        stmt = select(User).where(User.id == user_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        now = datetime.now(timezone.utc)
        user.status = UserStatusEnum.ACTIVE.value
        user.trial_starts_at = now
        user.trial_ends_at = now + timedelta(days=settings.TRIAL_DAYS)
        user.reminders_sent = 0

        # Ensure demo cameras created for merchant
        cam_stmt = select(Camera).where(Camera.org_id == user.org_id)
        cam_res = await session.execute(cam_stmt)
        if not cam_res.scalars().all():
            c1 = Camera(org_id=user.org_id, name="Камера 1 (Вход)", rtsp_url="demo://entrance", camera_type="entrance")
            c2 = Camera(org_id=user.org_id, name="Камера 2 (Касса)", rtsp_url="demo://checkout", camera_type="checkout", has_audio=True)
            session.add_all([c1, c2])

        await session.commit()
        merchant_tg_id = user.telegram_id
        lang = user.language or "ru"

    await callback.message.edit_text(f"✅ <b>Заявка #{user_id} ОДОБРЕНА!</b> Активирован 7-дневный триал.", parse_mode="HTML")

    # Send congratulation to merchant
    if lang == "uz":
        merchant_msg = (
            f"🎉 <b>Tabriklaymiz! Sizning arizangiz ma'qullandi!</b>\n\n"
            f"Sizga <b>7 kunlik bepul sinov davri</b> faollashtirildi.\n"
            f"Endi siz o'z kameralaringizni ulab, to'liq AI tahlilidan foydalanishingiz mumkin!\n\n"
            f"Quyidagi menyu orqali boshqaruv panelini oching:"
        )
    else:
        merchant_msg = (
            f"🎉 <b>Поздравляем! Ваша заявка одобрена!</b>\n\n"
            f"Вам успешно активирован <b>бесплатный пробный период на 7 дней</b>.\n"
            f"Теперь вы можете подключить ваши камеры и получать ежедневные отчеты по продажам и сотрудникам!\n\n"
            f"Пользуйтесь меню ниже:"
        )

    try:
        await bot.send_message(
            chat_id=merchant_tg_id,
            text=merchant_msg,
            parse_mode="HTML",
            reply_markup=get_main_keyboard(lang, days_left=7)
        )
        await bot.send_message(
            chat_id=merchant_tg_id,
            text="📖 Как подключить камеры к BrainCam AI:",
            reply_markup=get_camera_guide_keyboard(lang)
        )
    except Exception as e:
        logger.error(f"Failed to notify merchant: {e}")

@dp.callback_query(F.data.startswith("admin:reject:"))
async def admin_reject_merchant(callback: types.CallbackQuery, bot: Bot):
    user_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        stmt = select(User).where(User.id == user_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        if user:
            user.status = UserStatusEnum.REJECTED.value
            await session.commit()
            merchant_tg_id = user.telegram_id

    await callback.message.edit_text(f"❌ Заявка #{user_id} отклонена.", parse_mode="HTML")
    try:
        await bot.send_message(
            chat_id=merchant_tg_id,
            text="К сожалению, ваша заявка была отклонена администратором. Свяжитесь с поддержкой: @abdvoris07"
        )
    except Exception:
        pass

# ================= PAYMENT & SUBSCRIPTION FLOW =================

@dp.message(F.text.startswith("💳") | F.text.in_([
    "💳 Сколько осталось оплата", "💳 Qolgan muddat va to'lov",
    "/subscription", "/tariff", "/tariffs", "/pay"
]))
async def cmd_subscription_menu(message: types.Message):
    """Displays subscription info, payment card, and days left"""
    async with async_session() as session:
        user, _ = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"
        if not user:
            no_acc = "Tariflar bilan tanishish uchun avval ro'yxatdan o'ting: /start" if lang == "uz" else "Для доступа к тарифам сначала зарегистрируйтесь: /start"
            await message.answer(no_acc)
            return
        days = user.days_left()
        is_active = user.is_access_granted()

    if lang == "uz":
        status_line = f"⏳ Faol muddat: <b>{days} kun qoldi</b>" if is_active else "⏳ Holat: <b>Sinov muddati yakunlangan (0 kun)</b>"
        text = (
            f"💳 <b>BRAINCAM AI — OBUNA VA TO'LOV</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{status_line}\n"
            f"💰 Oylik to'lov: <b>{settings.SUBSCRIPTION_MONTHLY_PRICE}</b>\n\n"
            f"<b>To'lov uchun VISA karta rekvizitlari:</b>\n"
            f"💳 Karta raqami: <code>{settings.VISA_CARD_NUMBER}</code>\n"
            f"👤 Karta egasi: <b>{settings.VISA_CARD_HOLDER}</b>\n"
            f"💬 Egasi (Telegram): <b>@{settings.ADMIN_TELEGRAM_USERNAME}</b>\n\n"
            f"To'lovni amalga oshirgach, chekning skrinshotini (rasmini) shu yerga yuboring yoki @{settings.ADMIN_TELEGRAM_USERNAME} ga yozing!"
        )
    else:
        status_line = f"⏳ Доступ активен: <b>осталось {days} дн.</b>" if is_active else "⏳ Статус доступа: <b>Срок истек (0 дн.)</b>"
        text = (
            f"💳 <b>BRAINCAM AI — ТАРИФ И ОПЛАТА</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{status_line}\n"
            f"💰 Стоимость подписки: <b>{settings.SUBSCRIPTION_MONTHLY_PRICE}</b>\n\n"
            f"<b>Реквизиты для оплаты (VISA):</b>\n"
            f"💳 Номер карты: <code>{settings.VISA_CARD_NUMBER}</code>\n"
            f"👤 Держатель карты: <b>{settings.VISA_CARD_HOLDER}</b>\n"
            f"💬 Владелец (Telegram): <b>@{settings.ADMIN_TELEGRAM_USERNAME}</b>\n\n"
            f"После перевода просто <b>отправьте фото или скриншот чека</b> прямо в этот чат или напишите @{settings.ADMIN_TELEGRAM_USERNAME}!"
        )

    await message.answer(text, parse_mode="HTML")

# ================= MINI APP / DASHBOARD =================

@dp.message(F.text.in_([
    "📱 Войти в Mini App", "📱 Mini App-ga kirish",
    "📱 Открыть Mini App", "📱 Mini App-ni ochish",
    "📱 Открыть Dashboard в приложении", "📱 Dashboard ilovasini ochish",
    "/miniapp", "/app"
]))
async def cmd_open_miniapp(message: types.Message):
    """Direct access & guide for BrainCam Mini App / Dashboard"""
    async with async_session() as session:
        user, _ = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"

    if lang == "uz":
        text = (
            "📱 <b>BrainCam AI Mini App / Boshqaruv paneli</b>\n\n"
            "Ilovaga kirish va to'liq boshqaruv panelidan foydalanish uchun quyidagi tugmani bosing.\n\n"
            "<b>Ilova imkoniyatlari:</b>\n"
            "• 📊 Real vaqtdagi savdo, tashriflar va konversiya grafigi\n"
            "• 📹 Do'kon kameralari va jonli monitoring\n"
            "• 🎙 Ovozli tahlil: mijozlar e'tiroz va shikoyatlarini aniqlash\n"
            "• 💡 Daromadni oshirish bo'yicha sun'iy intellekt tavsiyalari\n\n"
            "👇 <i>Ilovani ochish uchun pastdagi tugmani bosing:</i>"
        )
    else:
        text = (
            "📱 <b>BrainCam AI Mini App / Панель управления</b>\n\n"
            "Для входа в приложение и работы с полным дашбордом нажмите кнопку ниже.\n\n"
            "<b>Возможности приложения:</b>\n"
            "• 📊 Графика продаж, трафика посетителей и конверсии в реальном времени\n"
            "• 📹 Подключенные камеры магазина и мониторинг касс\n"
            "• 🎙 Аудиоаналитика: детекция конфликтов и возражений клиентов\n"
            "• 💡 Рекомендации нейросети по росту среднего чека и выручки\n\n"
            "👇 <i>Нажмите кнопку ниже для запуска Mini App:</i>"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=get_miniapp_inline_keyboard(lang))

@dp.message(F.photo & ~F.caption.contains("cam:"))
async def handle_photo_receipt_or_analysis(message: types.Message, bot: Bot, state: FSMContext):
    """Handles both payment receipts and instant camera analysis photos"""
    async with async_session() as session:
        user, org = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"

    photo = message.photo[-1]

    # If caption or context indicates payment receipt, or user explicitly uploads a check
    caption = (message.caption or "").lower()
    if any(k in caption for k in ["чек", "оплата", "to'lov", "chek", "visa", "перевод", "квитанция"]):
        async with async_session() as session:
            receipt = PaymentReceipt(
                user_id=user.id if user else 1,
                telegram_file_id=photo.file_id,
                status="pending"
            )
            session.add(receipt)
            await session.commit()
            receipt_id = receipt.id

        confirm_msg = (
            "✅ <b>Чек об оплате принят!</b>\n"
            f"Владелец (@{settings.ADMIN_TELEGRAM_USERNAME}) уже получил ваш чек. "
            "После подтверждения ваш доступ будет продлен на 30 дней!"
        ) if lang == "ru" else (
            "✅ <b>To'lov cheki qabul qilindi!</b>\n"
            f"Administrator (@{settings.ADMIN_TELEGRAM_USERNAME}) chekni tekshirmoqda. "
            "Tasdiqlangach obunangiz 30 kunga uzaytiriladi!"
        )
        await message.reply(confirm_msg, parse_mode="HTML")

        # Send receipt to admin
        admin_cap = (
            f"💳 <b>НОВЫЙ ЧЕК ОБ ОПЛАТЕ ПОДПИСКИ!</b>\n"
            f"👤 Пользователь: {user.full_name if user else 'Клиент'} (@{message.from_user.username})\n"
            f"🏬 Магазин: {user.store_name if user else 'Магазин'}\n"
            f"💰 Сумма: {settings.SUBSCRIPTION_MONTHLY_PRICE}\n\n"
            f"Подтвердите или отклоните платеж:"
        )
        await notify_admin(bot, admin_cap, reply_markup=get_admin_payment_keyboard(receipt_id), photo_file_id=photo.file_id)
        return

    # Otherwise: regular camera frame vision analysis with Gemini 2.5 Flash Lite
    wait_text = "🔍 Gemini 2.5 Flash Lite orqali kadr tahlil qilinmoqda..." if lang == "uz" else "🔍 Анализирую кадр через Gemini 2.5 Flash Lite..."
    wait_msg = await message.answer(wait_text)
    file = await bot.get_file(photo.file_id)
    file_bytes_io = io.BytesIO()
    await bot.download_file(file.file_path, file_bytes_io)
    image_bytes = file_bytes_io.getvalue()

    ai_data = await gemini_service.analyze_frame(image_bytes, camera_type="checkout", language=lang)

    # Record to DB
    async with async_session() as session:
        if org:
            if ai_data.get("entries_detected", 0) > 0:
                await AnalyticsService.record_event(session, org.id, 1, EventTypeEnum.ENTRY.value, count=ai_data["entries_detected"])
            if ai_data.get("purchases_detected", 0) > 0:
                await AnalyticsService.record_event(session, org.id, 1, EventTypeEnum.PURCHASE.value, count=ai_data["purchases_detected"])

    await wait_msg.delete()
    res_text = NotificationService.format_camera_analysis_result(ai_data, language=lang)
    await message.reply(res_text, parse_mode="HTML")

@dp.callback_query(F.data.startswith("admin:pay_ok:"))
async def admin_approve_payment(callback: types.CallbackQuery, bot: Bot):
    payment_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        stmt = select(PaymentReceipt).where(PaymentReceipt.id == payment_id)
        res = await session.execute(stmt)
        receipt = res.scalar_one_or_none()
        if not receipt:
            await callback.answer("Чек не найден", show_alert=True)
            return

        receipt.status = "approved"
        user_stmt = select(User).where(User.id == receipt.user_id)
        user_res = await session.execute(user_stmt)
        user = user_res.scalar_one_or_none()

        if not user:
            await session.commit()
            await callback.message.edit_caption(caption="✅ Чек одобрен (пользователь не найден).", parse_mode="HTML")
            return

        # 1. Update status and subscription flags
        user.is_paid = True
        user.status = UserStatusEnum.ACTIVE.value
        user.reminders_sent = 0

        # 2. Add +30 days safely without offset-naive / offset-aware TypeError
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        paid_naive = (
            user.paid_until.astimezone(timezone.utc).replace(tzinfo=None)
            if (user.paid_until and user.paid_until.tzinfo)
            else (user.paid_until.replace(tzinfo=None) if user.paid_until else None)
        )
        base_time = paid_naive if (paid_naive and paid_naive > now_naive) else now_naive
        user.paid_until = base_time + timedelta(days=30)

        merchant_tg_id = user.telegram_id
        lang = user.language or "ru"
        days = user.days_left()

        await session.commit()

    await callback.message.edit_caption(caption=f"✅ <b>ОПЛАТА ПОДТВЕРЖДЕНА!</b> Доступ продлен на 30 дней.", parse_mode="HTML")

    msg = (
        f"🎉 <b>Ваша оплата успешно подтверждена!</b>\n"
        f"Подписка продлена на 30 дней (активна еще {days} дн.). Спасибо, что вы с BrainCam AI!"
    ) if lang == "ru" else (
        f"🎉 <b>To'lovingiz muvaffaqiyatli tasdiqlandi!</b>\n"
        f"Obunangiz 30 kunga uzaytirildi (yana {days} kun faol). BrainCam AI bilan birga bo'lganingiz uchun rahmat!"
    )

    try:
        await bot.send_message(chat_id=merchant_tg_id, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error notifying merchant of payment: {e}")

@dp.callback_query(F.data.startswith("admin:pay_no:"))
async def admin_reject_payment(callback: types.CallbackQuery, bot: Bot):
    payment_id = int(callback.data.split(":")[2])
    merchant_tg_id = None
    lang = "ru"
    async with async_session() as session:
        stmt = select(PaymentReceipt).where(PaymentReceipt.id == payment_id)
        res = await session.execute(stmt)
        receipt = res.scalar_one_or_none()
        if receipt:
            receipt.status = "rejected"
            user_stmt = select(User).where(User.id == receipt.user_id)
            user_res = await session.execute(user_stmt)
            user = user_res.scalar_one_or_none()
            if user:
                merchant_tg_id = user.telegram_id
                lang = user.language or "ru"
            await session.commit()

    await callback.message.edit_caption(caption="❌ Чек отклонен.", parse_mode="HTML")

    if merchant_tg_id:
        rej_msg = (
            "❌ <b>Ваш чек об оплате был отклонен.</b>\n"
            f"Пожалуйста, свяжитесь с поддержкой: @{settings.ADMIN_TELEGRAM_USERNAME}"
        ) if lang == "ru" else (
            "❌ <b>Siz yuborgan to'lov cheki rad etildi.</b>\n"
            f"Iltimos, administrator bilan bog'laning: @{settings.ADMIN_TELEGRAM_USERNAME}"
        )
        try:
            await bot.send_message(chat_id=merchant_tg_id, text=rej_msg, parse_mode="HTML")
        except Exception:
            pass

# ================= CUSTOM REPORT TIME =================

@dp.message(F.text.in_(["⏰ Время отчета", "⏰ Hisobot vaqti", "/time"]))
async def cmd_set_report_time(message: types.Message):
    """Allows merchant to select automated daily notification time"""
    async with async_session() as session:
        user, _ = await get_user_and_org(session, message.from_user)
        current_time = user.daily_report_time if user else "21:00"
        lang = user.language if user else "ru"

    if lang == "uz":
        text = (
            f"⏰ <b>Kunlik hisobot vaqtini sozlash</b>\n\n"
            f"Hozirgi hisobot yetkazish vaqti: <b>{current_time}</b>\n"
            f"Smena yopilishiga mos vaqtni tanlang:"
        )
    else:
        text = (
            f"⏰ <b>Настройка ежедневного времени отчета</b>\n\n"
            f"Текущее время доставки отчета: <b>{current_time}</b>\n"
            f"Выберите удобное время закрытия смены:"
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=get_report_time_inline_keyboard()
    )

@dp.callback_query(F.data.startswith("time:"))
async def callback_select_time(callback: types.CallbackQuery):
    new_time = callback.data.split(":")[1] + ":" + callback.data.split(":")[2]
    async with async_session() as session:
        user, _ = await get_user_and_org(session, callback.from_user)
        lang = user.language if user else "ru"
        if user:
            user.daily_report_time = new_time
            await session.commit()

    if lang == "uz":
        text = (
            f"✅ <b>Hisobot vaqti {new_time} ga o'rnatildi!</b>\n"
            f"Har kuni kechqurun soat {new_time} da bot sizga kun tahlilini (mijozlar oqimi, xaridlar, konversiya va shikoyatlar) avtomatik yuboradi."
        )
    else:
        text = (
            f"✅ <b>Время отчета установлено на {new_time}!</b>\n"
            f"Каждый вечер в {new_time} бот будет автоматически присылать вам анализ дня (трафик, покупки, конверсию и жалобы)."
        )

    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()

# ================= SETTINGS MENU =================

@dp.message(F.text.in_(["⚙️ Настройки", "⚙️ Sozlamalar", "/settings"]))
async def cmd_settings(message: types.Message):
    """Displays settings menu for language, report delivery time, and Mini App link"""
    async with async_session() as session:
        user, org = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"
        current_time = user.daily_report_time if user else "21:00"

    if lang == "uz":
        text = (
            f"⚙️ <b>Do'kon sozlamalari</b>\n\n"
            f"• 🌐 Tanlangan til: <b>O'zbekcha 🇺🇿</b>\n"
            f"• ⏰ Kunlik hisobot vaqti: <b>{current_time}</b>\n\n"
            f"Kerakli parametrni o'zgartirish uchun quyidagi tugmalardan birini bosing:"
        )
    else:
        text = (
            f"⚙️ <b>Настройки магазина</b>\n\n"
            f"• 🌐 Выбранный язык: <b>Русский 🇷🇺</b>\n"
            f"• ⏰ Время отправки отчета: <b>{current_time}</b>\n\n"
            f"Нажмите на нужную кнопку для изменения параметров:"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=get_settings_inline_keyboard(lang))

@dp.callback_query(F.data == "settings:lang")
async def callback_settings_lang(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Выберите язык интерфейса / Tilni tanlang:",
        reply_markup=get_language_inline_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "settings:time")
async def callback_settings_time(callback: types.CallbackQuery):
    async with async_session() as session:
        user, _ = await get_user_and_org(session, callback.from_user)
        current_time = user.daily_report_time if user else "21:00"
        lang = user.language if user else "ru"

    if lang == "uz":
        text = (
            f"⏰ <b>Kunlik hisobot vaqtini tanlang</b>\n\n"
            f"Hozirgi vaqt: <b>{current_time}</b>"
        )
    else:
        text = (
            f"⏰ <b>Выберите время ежедневного отчета</b>\n\n"
            f"Текущее время: <b>{current_time}</b>"
        )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_report_time_inline_keyboard())
    await callback.answer()

# ================= ABOUT / SERVICE INFO =================

@dp.message(F.text.in_(["ℹ️ О сервисе и пользе", "ℹ️ Xizmat haqida ma'lumot", "/info"]))
async def cmd_service_info(message: types.Message):
    async with async_session() as session:
        user, _ = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"

    if lang == "uz":
        text = (
            "ℹ️ <b>BrainCam AI — Xizmat haqida va biznesingizga foydasi:</b>\n\n"
            "• 👥 <b>Haqiqiy tashrifchilar oqimi:</b> Do'koningizga qancha odam kirdi va qancha xarid bo'ldi (Konversiya %).\n"
            "• 👔 <b>Xodimlar va kassirlar nazorati:</b> Xodimlar ish joyidami, qachon keldi, telefonga chalg'iganmi yoki yo'q.\n"
            "• 🎙 <b>Ovozli tahlil:</b> Mikrofon orqali mijozlarning e'tiroz va shikoyatlarini avtomatik aniqlash.\n"
            "• 💡 <b>AI Maslahatlar:</b> Savdoni va o'rtacha chekni oshirish bo'yicha har kuni yangi tavsiyalar.\n"
            "• ⏰ <b>Kunlik Telegram hisobot:</b> Har kuni kechqurun smena yopilganda batafsil hisobot.\n\n"
            "🎁 <b>Barcha yangi foydalanuvchilar uchun 7 kunlik to'liq bepul sinov davri!</b>"
        )
    else:
        text = (
            "ℹ️ <b>BrainCam AI — О сервисе и пользе для вашего бизнеса:</b>\n\n"
            "• 👥 <b>Точный трафик:</b> Сколько человек зашло в магазин и сколько реально купило (Конверсия %).\n"
            "• 👔 <b>Контроль персонала:</b> На месте ли сотрудники, скорость обслуживания, нет ли зависания в телефонах.\n"
            "• 🎙 <b>Аудиоконтроль:</b> Детекция жалоб клиентов и конфликтов через микрофон камеры.\n"
            "• 💡 <b>AI-рекомендации:</b> Советы по выкладке, кассам и персоналу для роста вашей прибыли.\n"
            "• ⏰ <b>Ежедневные отчеты:</b> Автоматический вечерний дайджест в Telegram в выбранный час.\n\n"
            "🎁 <b>Для новых пользователей доступен 7-дневный бесплатный пробный период!</b>"
        )
    await message.answer(text, parse_mode="HTML")

# ================= AI CONVERSATIONAL & INTRO =================

@dp.message(F.text.in_(["💬 Чат с AI консультантом", "💬 AI bilan suhbat", "/ai"]))
async def cmd_ai_chat_intro(message: types.Message):
    async with async_session() as session:
        user, _ = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"

    if lang == "uz":
        text = (
            "💬 <b>BrainCam AI Biznes-Konsultant</b>\n\n"
            "Do'koningiz savdosi, xodimlar yoki mijozlar oqimi haqidagi har qanday savolni to'g'ridan-to'g'ri shu chatga yozing!\n\n"
            "<b>Namunaviy savollar:</b>\n"
            "• <i>«Bugungi konversiya va xaridlar soni qanday?»</i>\n"
            "• <i>«Nega soat 17:00 da kassada navbat yuzaga keldi?»</i>\n"
            "• <i>«Do'konimda o'rtacha chekni qanday qilib oshirish mumkin?»</i>"
        )
    else:
        text = (
            "💬 <b>AI Бизнес-Консультант BrainCam</b>\n\n"
            "Задайте любой вопрос о продажах, персонале или трафике вашего магазина прямо в этот чат!\n\n"
            "<b>Примеры вопросов:</b>\n"
            "• <i>«Сколько людей зашло сегодня и какая конверсия?»</i>\n"
            "• <i>«Были ли сегодня очереди на кассе?»</i>\n"
            "• <i>«Как увеличить средний чек на этой неделе?»</i>"
        )
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text.in_(["🔍 AI Анализ кадра/аудио", "🔍 Kadr/Ovoz AI tahlili", "/analyze"]))
async def cmd_frame_analysis_intro(message: types.Message):
    async with async_session() as session:
        user, _ = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"

    if lang == "uz":
        text = (
            "🔍 <b>Kadr yoki audio tezkor AI tahlili</b>\n\n"
            "Ushbu chatga kameradan olingan fotosurat yoki audio yozuv yuboring. Gemini neyrotarmog'i darhol tahlil qiladi:\n"
            "• Tashrifchilar va kassirlar soni\n"
            "• Navbatlar va xizmat ko'rsatish tezligi\n"
            "• Xodimlar harakati va xatti-harakati\n"
            "• E'tirozlar, bahslar yoki mijozlar kayfiyati\n\n"
            "📸 <i>Hozir surat yuborib ko'ring!</i>"
        )
    else:
        text = (
            "🔍 <b>Мгновенный AI Анализ кадра или аудио</b>\n\n"
            "Отправьте фото (снимок с камеры магазина) или аудиозапись прямо в этот чат. Нейросеть Gemini мгновенно определит:\n"
            "• Количество покупателей и кассиров\n"
            "• Длину очередей и скорость обслуживания\n"
            "• Поведение сотрудников у кассы\n"
            "• Жалобы, споры или эмоциональный фон\n\n"
            "📸 <i>Отправьте фото прямо сейчас!</i>"
        )
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text & ~F.text.startswith("/") & ~F.text.startswith("💳") & ~F.text.in_([
    "📊 Отчет за сегодня", "📊 Bugungi hisobot", "📊 Kunlik Hisobot",
    "💳 Сколько осталось оплата", "💳 Qolgan muddat va to'lov",
    "📱 Войти в Mini App", "📱 Mini App-ga kirish",
    "📱 Открыть Mini App", "📱 Mini App-ni ochish",
    "📱 Открыть Dashboard в приложении", "📱 Dashboard ilovasini ochish",
    "📹 Мои Камеры", "📹 Kameralarim",
    "💬 Чат с AI консультантом", "💬 AI bilan suhbat",
    "🔍 AI Анализ кадра/аудио", "🔍 Kadr/Ovoz AI tahlili",
    "🌐 Сменить язык", "🌐 Tilni o'zgartirish",
    "📝 Подключить 7 дней бесплатно", "📝 7 kunlik bepul sinovga ulanish",
    "📝 Заполнить заявку в чате", "📝 Arizani chatda to'ldirish",
    "⏰ Время отчета", "⏰ Hisobot vaqti",
    "⚙️ Настройки", "⚙️ Sozlamalar",
    "ℹ️ О сервисе и пользе", "ℹ️ Xizmat haqida ma'lumot"
]))
async def handle_ai_chat_question(message: types.Message):
    """Answers store owner's free-form questions using real store metrics and Gemini"""
    async with async_session() as session:
        user, org = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"
        if not user or not user.is_access_granted():
            no_acc = "AI maslahatchidan foydalanish uchun avval ro'yxatdan o'ting: /start" if lang == "uz" else "Для доступа к AI-консультанту сначала завершите регистрацию: /start"
            await message.answer(no_acc)
            return

        metrics = await AnalyticsService.get_daily_metrics(session, org.id if org else 1)

    wait_text = "🧠 Do'kon ma'lumotlari tahlil qilinmoqda..." if lang == "uz" else "🧠 Анализирую данные магазина..."
    wait_msg = await message.answer(wait_text)
    answer = await gemini_service.answer_merchant_question(
        question=message.text,
        store_context=metrics,
        language=lang
    )
    await wait_msg.delete()
    await message.reply(answer)

# ================= CAMERA GUIDE & SNAPSHOTS =================

@dp.callback_query(F.data == "cam:guide")
async def show_camera_guide(callback: types.CallbackQuery):
    async with async_session() as session:
        user, _ = await get_user_and_org(session, callback.from_user)
        lang = user.language if user else "ru"

    if lang == "uz":
        guide_text = (
            "📹 <b>KAMERALARNI BRAINCAM AI GA ULASH QO'LLANMASI</b>\n\n"
            "<b>1-usul (Standart RTSP oqimi):</b>\n"
            "Agar do'kondagi routerda port yo'naltirilgan bo'lsa (554-port) yoki statik oq IP bo'lsa:\n"
            "• Hikvision: <code>rtsp://admin:parol@IP:554/Streaming/Channels/101</code>\n"
            "• Dahua: <code>rtsp://admin:parol@IP:554/cam/realmonitor?channel=1&subtype=0</code>\n\n"
            "<b>2-usul (Oq IP bo'lmasa — Local Edge Agent):</b>\n"
            "Do'kondagi kompyuterda (kassa yoki mini-PC) kichik agentni ishga tushiring:\n"
            "<code>python braincam_agent.py --rtsp rtsp://192.168.1.101:554/live</code>\n"
            "Agent kadrlarni xavfsiz shifrlab BrainCam AI serveriga yuboradi!\n\n"
            "<b>3-usul (Ommaviy import):</b>\n"
            "Mini App va Dashboard orqali lokal tarmoqni avtoskanerlash yoki CSV fayl orqali bir vaqtning o'zida yuzlab kameralarni qo'shish mumkin!"
        )
    else:
        guide_text = (
            "📹 <b>КАК ИНТЕГРИРОВАТЬ ВАШИ КАМЕРЫ В BRAINCAM AI</b>\n\n"
            "<b>Вариант 1 (Стандартный RTSP):</b>\n"
            "Если на роутере магазина настроен проброс портов (порт 554) или есть белый IP:\n"
            "• Hikvision: <code>rtsp://admin:пароль@IP:554/Streaming/Channels/101</code>\n"
            "• Dahua: <code>rtsp://admin:пароль@IP:554/cam/realmonitor?channel=1&subtype=0</code>\n\n"
            "<b>Вариант 2 (Без белого IP — Local Edge Agent):</b>\n"
            "Запустите легкий агент на компьютере магазина (кассовый ПК или Windows/Linux mini-PC):\n"
            "<code>python braincam_agent.py --rtsp rtsp://192.168.1.101:554/live</code>\n"
            "Агент сам шифрует и передает кадры на сервер BrainCam AI!\n\n"
            "<b>Вариант 3 (Массовая интеграция):</b>\n"
            "В Dashboard доступен автосканер сети магазина и импорт через CSV-файл сотен камер сразу!"
        )
    await callback.message.answer(guide_text, parse_mode="HTML")
    await callback.answer()

@dp.message(F.text.in_(["📊 Отчет за сегодня", "📊 Bugungi hisobot", "📊 Kunlik Hisobot", "/report"]))
async def cmd_daily_report(message: types.Message):
    async with async_session() as session:
        user, org = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"
        store_name = user.store_name or (org.name if org else "Магазин")

        if not user or not user.is_access_granted():
            no_acc_text = "Kirish hali faollashtirilmagan. Ro'yxatdan o'tish holatini /start orqali tekshiring" if lang == "uz" else "Доступ еще не активирован. Проверьте статус регистрации в /start"
            await message.answer(no_acc_text)
            return

    wait_text = "⏳ Ma'lumotlar to'planmoqda va AI tahlili tayyorlanmoqda..." if lang == "uz" else "⏳ Собираем данные и формируем AI-анализ..."
    wait_msg = await message.answer(wait_text)
    async with async_session() as session:
        report = await AnalyticsService.generate_or_update_daily_report(session, org.id if org else 1)
        report_text = NotificationService.format_daily_digest(report, store_name=store_name, language=lang)

    await wait_msg.delete()
    await message.answer(report_text, parse_mode="HTML")

@dp.message(F.text.in_(["📹 Мои Камеры", "📹 Kameralarim", "/cameras"]))
async def cmd_cameras(message: types.Message):
    async with async_session() as session:
        user, org = await get_user_and_org(session, message.from_user)
        lang = user.language if user else "ru"
        if not user or not user.is_access_granted():
            no_acc_text = "Avval ro'yxatdan o'tishni yakunlang: /start" if lang == "uz" else "Сначала завершите регистрацию: /start"
            await message.answer(no_acc_text)
            return

        stmt = select(Camera).where(Camera.org_id == (org.id if org else 1))
        res = await session.execute(stmt)
        cameras = res.scalars().all()

    if not cameras:
        no_cam_text = "Kameralar hali qo'shilmagan." if lang == "uz" else "Камеры еще не добавлены."
        await message.answer(no_cam_text, reply_markup=get_camera_guide_keyboard(lang))
        return

    for cam in cameras:
        if lang == "uz":
            cam_info = (
                f"📹 <b>{cam.name}</b>\n"
                f"📍 Hudud: <code>{cam.camera_type}</code> | 🟢 <b>{cam.status}</b>\n"
                f"🔗 RTSP: <code>{cam.rtsp_url}</code>"
            )
        else:
            cam_info = (
                f"📹 <b>{cam.name}</b>\n"
                f"📍 Зона: <code>{cam.camera_type}</code> | 🟢 <b>{cam.status}</b>\n"
                f"🔗 RTSP: <code>{cam.rtsp_url}</code>"
            )
        await message.answer(cam_info, parse_mode="HTML", reply_markup=get_camera_actions_inline(cam.id, lang))

    guide_prompt = "Ulash bo'yicha qo'llanma:" if lang == "uz" else "Инструкция по подключению:"
    await message.answer(guide_prompt, reply_markup=get_camera_guide_keyboard(lang))

@dp.callback_query(F.data.startswith("cam:"))
async def callback_cam_action(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    action = parts[1]
    if action == "guide":
        return

    cam_id = int(parts[2])
    async with async_session() as session:
        user, _ = await get_user_and_org(session, callback.from_user)
        lang = user.language if user else "ru"
        cam_stmt = select(Camera).where(Camera.id == cam_id)
        cam_res = await session.execute(cam_stmt)
        cam = cam_res.scalar_one_or_none()

    if not cam:
        not_found_msg = "Kamera topilmadi" if lang == "uz" else "Камера не найдена"
        await callback.answer(not_found_msg)
        return

    if action == "snap":
        snap_wait = "📸 Kadr olinmoqda..." if lang == "uz" else "📸 Получаем снимок..."
        await callback.answer(snap_wait)
        frame = RTSPCaptureService.get_snapshot(cam.rtsp_url)
        photo = BufferedInputFile(frame, filename="snapshot.jpg")
        cap_text = f"📹 <b>{cam.name}</b> kamerasidan kadr" if lang == "uz" else f"📹 Кадр с камеры <b>{cam.name}</b>"
        await callback.message.answer_photo(photo, caption=cap_text, parse_mode="HTML")
    elif action == "analyze":
        analyze_wait = "⚡️ AI tahlil qilmoqda..." if lang == "uz" else "⚡️ AI анализирует..."
        await callback.answer(analyze_wait)
        frame = RTSPCaptureService.get_snapshot(cam.rtsp_url)
        ai_data = await gemini_service.analyze_frame(frame, camera_type=cam.camera_type, language=lang)
        res_text = NotificationService.format_camera_analysis_result(ai_data, language=lang)
        photo = BufferedInputFile(frame, filename="analyzed.jpg")
        await callback.message.answer_photo(photo, caption=res_text, parse_mode="HTML")
    elif action == "test":
        ok, msg = RTSPCaptureService.test_connection(cam.rtsp_url)
        alert_msg = f"Holat: {msg}" if lang == "uz" else f"Статус: {msg}"
        await callback.answer(alert_msg, show_alert=True)

@dp.message(F.text.in_(["🌐 Сменить язык", "🌐 Tilni o'zgartirish", "/language"]))
async def cmd_language(message: types.Message):
    await message.answer(
        "Выберите язык интерфейса / Tilni tanlang:",
        reply_markup=get_language_inline_keyboard()
    )

@dp.callback_query(F.data.startswith("lang:"))
async def callback_language(callback: types.CallbackQuery):
    new_lang = callback.data.split(":")[1]
    async with async_session() as session:
        user, org = await get_user_and_org(session, callback.from_user)
        if user:
            user.language = new_lang
        if org:
            org.language = new_lang
        await session.commit()
        days = user.days_left() if user else 7

    msg = "✅ Язык изменен на Русский!" if new_lang == "ru" else "✅ Til O'zbekchaga o'zgartirildi!"
    await callback.message.edit_text(msg)
    await callback.message.answer("Главное меню / Asosiy menyu:", reply_markup=get_main_keyboard(new_lang, days_left=days))
    await callback.answer()

async def run_bot():
    """Starts Telegram Bot polling"""
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN.startswith("your_"):
        logger.warning("TELEGRAM_BOT_TOKEN is not configured in .env.")
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    await init_db()
    logger.info("Starting BrainCam AI Bot with Onboarding, Admin Approval & Subscription...")
    await dp.start_polling(bot)
