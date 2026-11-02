import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from braincam.db.session import init_db, async_session
from braincam.db.models import User, Organization, PaymentReceipt, UserStatusEnum
from braincam.config import settings
from braincam.services.scheduler_service import BrainCamScheduler
from braincam.bot.main_bot import admin_approve_payment, admin_reject_payment

class TestBillingAndSubscription(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        await init_db()
        from sqlalchemy import delete
        async with async_session() as session:
            await session.execute(delete(User).where(User.telegram_id.in_([1001, 1002, 1003, 2001, 2002, 2003, 3001])))
            await session.commit()

    async def test_days_left_and_is_access_granted_datetime_safety(self):
        """Verifies offset-naive and offset-aware datetimes do not raise TypeError"""
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        now_aware_utc = datetime.now(timezone.utc)
        tashkent_tz = timezone(timedelta(hours=5))
        now_aware_tashkent = datetime.now(tashkent_tz)

        # 1. Active trial with offset-naive datetime
        u1 = User(
            telegram_id=1001,
            status=UserStatusEnum.ACTIVE.value,
            is_paid=False,
            trial_ends_at=now_naive + timedelta(days=5, hours=2)
        )
        self.assertTrue(u1.is_access_granted())
        self.assertEqual(u1.days_left(), 5)

        # 2. Active trial with offset-aware UTC datetime
        u2 = User(
            telegram_id=1002,
            status=UserStatusEnum.ACTIVE.value,
            is_paid=False,
            trial_ends_at=now_aware_utc + timedelta(days=3, hours=1)
        )
        self.assertTrue(u2.is_access_granted())
        self.assertEqual(u2.days_left(), 3)

        # 3. Active trial with offset-aware non-UTC datetime (Tashkent +05:00)
        u3 = User(
            telegram_id=1003,
            status=UserStatusEnum.ACTIVE.value,
            is_paid=False,
            trial_ends_at=now_aware_tashkent + timedelta(days=2, hours=1)
        )
        self.assertTrue(u3.is_access_granted())
        self.assertEqual(u3.days_left(), 2)

        # 4. Paid subscription with offset-naive datetime
        u4 = User(
            telegram_id=1004,
            status=UserStatusEnum.ACTIVE.value,
            is_paid=True,
            paid_until=now_naive + timedelta(days=30)
        )
        self.assertTrue(u4.is_access_granted())
        self.assertGreaterEqual(u4.days_left(), 29)

        # 5. Expired trial with offset-naive datetime
        u5 = User(
            telegram_id=1005,
            status=UserStatusEnum.ACTIVE.value,
            is_paid=False,
            trial_ends_at=now_naive - timedelta(hours=1)
        )
        self.assertFalse(u5.is_access_granted())
        self.assertEqual(u5.days_left(), 0)

        # 6. User with EXPIRED status
        u6 = User(
            telegram_id=1006,
            status=UserStatusEnum.EXPIRED.value,
            is_paid=False,
            trial_ends_at=now_naive + timedelta(days=5)
        )
        self.assertFalse(u6.is_access_granted())

    async def test_scheduler_3_day_countdown_reminders_and_anti_spam(self):
        """Verifies countdown reminders (Days 5, 6, 7), VISA details and spam prevention"""
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

        async with async_session() as session:
            # Create 3 users corresponding to Day 5, Day 6, Day 7 of 7-day trial
            # Day 5: 2 days left
            u_day5 = User(
                telegram_id=2001,
                username="user_day5",
                full_name="User Day 5",
                status=UserStatusEnum.ACTIVE.value,
                is_paid=False,
                trial_ends_at=now_naive + timedelta(days=2, hours=12),
                reminders_sent=0,
                language="ru"
            )
            # Day 6: 1 day left
            u_day6 = User(
                telegram_id=2002,
                username="user_day6",
                full_name="User Day 6",
                status=UserStatusEnum.ACTIVE.value,
                is_paid=False,
                trial_ends_at=now_naive + timedelta(days=1, hours=6),
                reminders_sent=1,
                language="uz"
            )
            # Day 7: 0 days left (<24 hours remaining)
            u_day7 = User(
                telegram_id=2003,
                username="user_day7",
                full_name="User Day 7",
                status=UserStatusEnum.ACTIVE.value,
                is_paid=False,
                trial_ends_at=now_naive + timedelta(hours=8),
                reminders_sent=2,
                language="ru"
            )
            session.add_all([u_day5, u_day6, u_day7])
            await session.commit()

        mock_bot = AsyncMock()

        # Run scheduler tick 1
        await BrainCamScheduler.check_trial_reminders(mock_bot)

        self.assertEqual(mock_bot.send_message.call_count, 3)

        # Verify message contents contain VISA details:
        # Card: 4916 9903 6185 3101
        # Holder: Abduvoris Rahimjonov
        # Owner Telegram: @abdvoris07
        sent_calls = mock_bot.send_message.call_args_list
        for call in sent_calls:
            msg_text = call.kwargs["text"]
            self.assertIn("4916 9903 6185 3101", msg_text)
            self.assertIn("Abduvoris Rahimjonov", msg_text)
            self.assertIn("@abdvoris07", msg_text)

        # Verify reminders_sent was incremented to prevent spam
        async with async_session() as session:
            for tg_id, expected_reminders in [(2001, 1), (2002, 2), (2003, 3)]:
                from sqlalchemy import select
                u = (await session.execute(select(User).where(User.telegram_id == tg_id))).scalar_one()
                self.assertEqual(u.reminders_sent, expected_reminders)

        # Anti-spam verification: Running scheduler tick 2 should NOT send any more reminders!
        mock_bot.send_message.reset_mock()
        await BrainCamScheduler.check_trial_reminders(mock_bot)
        self.assertEqual(mock_bot.send_message.call_count, 0)

    async def test_admin_receipt_approval_flow(self):
        """Verifies receipt approval -> +30 days, status=active, confirmation to user"""
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

        async with async_session() as session:
            # Merchant whose trial had expired
            merchant = User(
                telegram_id=3001,
                username="test_merchant",
                full_name="Test Merchant",
                store_name="Super Store",
                status=UserStatusEnum.EXPIRED.value,
                is_paid=False,
                trial_ends_at=now_naive - timedelta(days=2),
                paid_until=None,
                reminders_sent=3,
                language="ru"
            )
            session.add(merchant)
            await session.flush()

            # Uploaded receipt
            receipt = PaymentReceipt(
                user_id=merchant.id,
                telegram_file_id="photo_file_12345",
                status="pending"
            )
            session.add(receipt)
            await session.commit()
            receipt_id = receipt.id

        mock_bot = AsyncMock()
        mock_callback = AsyncMock()
        mock_callback.data = f"admin:pay_ok:{receipt_id}"
        mock_callback.message = AsyncMock()

        # Admin clicks Approve
        await admin_approve_payment(mock_callback, mock_bot)

        # Verify DB updates
        async with async_session() as session:
            from sqlalchemy import select
            updated_receipt = (await session.execute(
                select(PaymentReceipt).where(PaymentReceipt.id == receipt_id)
            )).scalar_one()
            self.assertEqual(updated_receipt.status, "approved")

            updated_user = (await session.execute(
                select(User).where(User.telegram_id == 3001)
            )).scalar_one()

            # 1. User gets +30 days
            self.assertTrue(updated_user.is_paid)
            self.assertIsNotNone(updated_user.paid_until)
            expected_min = now_naive + timedelta(days=29)
            self.assertGreater(updated_user.paid_until, expected_min)

            # 2. Status updated to ACTIVE
            self.assertEqual(updated_user.status, UserStatusEnum.ACTIVE.value)
            self.assertTrue(updated_user.is_access_granted())
            self.assertGreaterEqual(updated_user.days_left(), 29)

            # 3. Reminders reset
            self.assertEqual(updated_user.reminders_sent, 0)

        # 4. Confirmation sent to merchant
        mock_bot.send_message.assert_called_once()
        sent_to = mock_bot.send_message.call_args.kwargs["chat_id"]
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        self.assertEqual(sent_to, 3001)
        self.assertIn("30 дней", sent_text)
        self.assertIn("успешно подтверждена", sent_text)

if __name__ == "__main__":
    unittest.main()
