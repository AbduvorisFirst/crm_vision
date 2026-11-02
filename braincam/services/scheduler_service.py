import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from aiogram import Bot

from braincam.config import settings
from braincam.db.session import async_session
from braincam.db.models import User, Organization, DailyReport, UserStatusEnum
from braincam.services.analytics_service import AnalyticsService
from braincam.services.notification_service import NotificationService

logger = logging.getLogger("braincam.scheduler")

class BrainCamScheduler:
    """
    Automated background worker:
      1. Dispatches daily KPI store report at merchant's customized report time (e.g. 21:00).
      2. Sends 3 reminder notices during the final 3 days of the 7-day free trial.
      3. Handles trial expiration if payment is not uploaded.
    """

    @classmethod
    async def start(cls, bot: Bot):
        logger.info("BrainCamScheduler started.")
        while True:
            try:
                await cls.check_daily_reports(bot)
                await cls.check_trial_reminders(bot)
            except Exception as e:
                logger.error(f"Error in scheduler tick: {e}")
            await asyncio.sleep(60) # Run every minute

    @classmethod
    async def check_daily_reports(cls, bot: Bot):
        # Current local hour:minute (e.g. "21:00") in Tashkent timezone (UTC+5)
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc + timedelta(hours=5)
        current_hm = now_local.strftime("%H:%M")
        today_date = now_local.strftime("%Y-%m-%d")

        async with async_session() as session:
            stmt = select(User).where(
                User.status == UserStatusEnum.ACTIVE.value,
                User.daily_report_time == current_hm
            )
            res = await session.execute(stmt)
            users = res.scalars().all()

            for user in users:
                if not user.org_id:
                    continue

                # Check if report was already sent today
                rep_stmt = select(DailyReport).where(
                    DailyReport.org_id == user.org_id,
                    DailyReport.date == today_date,
                    DailyReport.sent_to_telegram == True
                )
                rep_res = await session.execute(rep_stmt)
                if rep_res.scalar_one_or_none():
                    continue

                # Generate and deliver report
                report = await AnalyticsService.generate_or_update_daily_report(session, user.org_id)
                report.sent_to_telegram = True
                await session.commit()

                org_stmt = select(Organization).where(Organization.id == user.org_id)
                org_res = await session.execute(org_stmt)
                org = org_res.scalar_one_or_none()
                store_name = user.store_name or (org.name if org else "Магазин")

                report_text = NotificationService.format_daily_digest(
                    report,
                    store_name=store_name,
                    language=user.language or "ru"
                )

                try:
                    await bot.send_message(chat_id=user.telegram_id, text=report_text, parse_mode="HTML")
                    logger.info(f"Delivered automated daily report to user {user.telegram_id} ({store_name})")
                except Exception as e:
                    logger.error(f"Failed to deliver automated report to {user.telegram_id}: {e}")

    @classmethod
    async def check_trial_reminders(cls, bot: Bot):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with async_session() as session:
            stmt = select(User).where(
                User.status == UserStatusEnum.ACTIVE.value,
                User.is_paid == False,
                User.trial_ends_at.isnot(None)
            )
            res = await session.execute(stmt)
            users = res.scalars().all()

            for user in users:
                trial_target = user.trial_ends_at.replace(tzinfo=None)
                diff = trial_target - now
                days_left = diff.days

                # 3 Reminders in the last 3 days:
                # Reminder 1: 3 days left
                # Reminder 2: 2 days left
                # Reminder 3: 1 day or hours left
                if days_left == 2 and user.reminders_sent < 1:
                    await cls._send_payment_reminder(bot, user, reminder_num=1, days_left=days_left)
                    user.reminders_sent = 1
                elif days_left == 1 and user.reminders_sent < 2:
                    await cls._send_payment_reminder(bot, user, reminder_num=2, days_left=days_left)
                    user.reminders_sent = 2
                elif days_left == 0 and user.reminders_sent < 3 and diff.total_seconds() > 0:
                    await cls._send_payment_reminder(bot, user, reminder_num=3, days_left=days_left)
                    user.reminders_sent = 3
                elif diff.total_seconds() <= 0:
                    user.status = UserStatusEnum.EXPIRED.value
                    await cls._send_expired_notice(bot, user)

            await session.commit()

    @classmethod
    async def _send_payment_reminder(cls, bot: Bot, user: User, reminder_num: int, days_left: int):
        lang = user.language or "ru"
        if lang == "uz":
            text = (
                f"⚠️ <b>ESLATMA #{reminder_num}: SINOV MUDDATI TUGAMOQDA!</b>\n\n"
                f"Sizning 7 kunlik bepul sinov davringiz tugashiga <b>{days_left} kun qoldi</b>.\n\n"
                f"BrainCam AI xizmatlaridan uzluksiz foydalanish va kunlik hisobotlarni olishni davom ettirish uchun to'lovni amalga oshiring:\n\n"
                f"💳 <b>VISA karta:</b> <code>{settings.VISA_CARD_NUMBER}</code>\n"
                f"👤 <b>Qabul qiluvchi:</b> {settings.VISA_CARD_HOLDER}\n"
                f"💰 <b>Narxi:</b> {settings.SUBSCRIPTION_MONTHLY_PRICE}\n\n"
                f"To'lov qilgach, chek rasmini to'g'ridan-to'g'ri shu botga yuboring!"
            )
        else:
            text = (
                f"⚠️ <b>НАПОМИНАНИЕ #{reminder_num}: ПРОБНЫЙ ПЕРИОД ЗАКАНЧИВАЕТСЯ!</b>\n\n"
                f"До окончания вашего 7-дневного бесплатного периода осталось <b>{days_left} дн.</b>\n\n"
                f"Чтобы не потерять аналитику, контроль сотрудников и доступ к камерам, продлите подписку:\n\n"
                f"💳 <b>Карта VISA:</b> <code>{settings.VISA_CARD_NUMBER}</code>\n"
                f"👤 <b>Получатель:</b> {settings.VISA_CARD_HOLDER}\n"
                f"💰 <b>Стоимость:</b> {settings.SUBSCRIPTION_MONTHLY_PRICE}\n\n"
                f"После перевода отправьте скриншот/фото чека в этот чат!"
            )
        try:
            await bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="HTML")
        except Exception:
            pass

    @classmethod
    async def _send_expired_notice(cls, bot: Bot, user: User):
        lang = user.language or "ru"
        msg = (
            "🔒 <b>Срок бесплатного пробного периода истек!</b>\n\n"
            f"Для возобновления работы переведите оплату на карту VISA:\n"
            f"<code>{settings.VISA_CARD_NUMBER}</code> ({settings.VISA_CARD_HOLDER})\n"
            "и отправьте фото чека в этот чат. Доступ будет моментально продлен!"
        ) if lang == "ru" else (
            "🔒 <b>Bepul sinov muddati yakunlandi!</b>\n\n"
            f"Xizmatni davom ettirish uchun to'lovni VISA kartasiga o'tkazing:\n"
            f"<code>{settings.VISA_CARD_NUMBER}</code> ({settings.VISA_CARD_HOLDER})\n"
            "va chek rasmini shu yerga yuboring. Kirish darhol tiklanadi!"
        )
        try:
            await bot.send_message(chat_id=user.telegram_id, text=msg, parse_mode="HTML")
        except Exception:
            pass
