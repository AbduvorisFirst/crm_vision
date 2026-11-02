from typing import Dict, Any, List
from braincam.db.models import DailyReport, Alert

class NotificationService:
    """
    Bilingual (Russian 🇷🇺 and Uzbek 🇺🇿) notification generator for Telegram Bot.
    Formats:
      - Daily store performance digest (Visitors, Purchases, Conversion, Peak hours, Staff score, Audio complaints, AI recommendations)
      - Instant alerts (Staff distracted/absent, customer conflict/complaint, queue overflow)
    """

    @staticmethod
    def format_daily_digest(report: DailyReport, store_name: str, language: str = "ru") -> str:
        """Formats comprehensive daily Telegram digest for the merchant"""
        if language == "uz":
            return (
                f"📊 <b>BRAINCAM AI — KUNLIK HISOBOT</b>\n"
                f"🏬 <b>Do'kon:</b> {store_name}\n"
                f"📅 <b>Sana:</b> {report.date}\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"👥 <b>Tashrif buyuruvchilar:</b> {report.visitors_count} kishi\n"
                f"🛍 <b>Xaridlar soni:</b> {report.buyers_count} ta\n"
                f"📈 <b>Konversiya (savdo ulushi):</b> <b>{report.conversion_rate:.1f}%</b>\n"
                f"⏰ <b>Eng gavjum vaqt:</b> {report.peak_hour}\n\n"
                f"👔 <b>Xodimlar bahosi:</b> ⭐ {report.employee_score:.1f}/5.0\n"
                f"💬 <i>{report.employee_notes or 'Xodimlar odatiy rejimda ishladi.'}</i>\n\n"
                f"🎙 <b>Mijozlar shikoyatlari:</b> {report.complaints_count} ta\n\n"
                f"💡 <b>BrainCam AI Maslahatlari:</b>\n"
                f"{report.ai_recommendations or '• Bugun hech qanday jiddiy kamchiliklar aniqlanmadi.'}\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<i>BrainCam AI — Har bir kamerani aqlli qiling!</i>"
            )
        else:
            return (
                f"📊 <b>BRAINCAM AI — ЕЖЕДНЕВНЫЙ ОТЧЕТ</b>\n"
                f"🏬 <b>Магазин:</b> {store_name}\n"
                f"📅 <b>Дата:</b> {report.date}\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"👥 <b>Посетителей (трафик):</b> {report.visitors_count} чел.\n"
                f"🛍 <b>Совершили покупку:</b> {report.buyers_count} клиентов\n"
                f"📈 <b>Конверсия:</b> <b>{report.conversion_rate:.1f}%</b>\n"
                f"⏰ <b>Пиковый час:</b> {report.peak_hour}\n\n"
                f"👔 <b>Оценка работы сотрудников:</b> ⭐ {report.employee_score:.1f}/5.0\n"
                f"💬 <i>{report.employee_notes or 'Персонал работал стабильно.'}</i>\n\n"
                f"🎙 <b>Жалоб зафиксировано (аудио):</b> {report.complaints_count} шт.\n\n"
                f"💡 <b>Рекомендации AI для владельца:</b>\n"
                f"{report.ai_recommendations or '• Сегодня нарушений и критических просадок не выявлено.'}\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<i>BrainCam AI — Делаем каждую камеру интеллектуальной!</i>"
            )

    @staticmethod
    def format_instant_alert(
        alert_type: str,
        camera_name: str,
        message: str,
        language: str = "ru"
    ) -> str:
        """Formats high-priority alert for immediate Telegram notification"""
        if language == "uz":
            titles = {
                "employee_alert": "⚠️ <b>XODIM BO'YICHA OGOHLANTIRISH</b>",
                "complaint": "🚨 <b>MIJOZDAN SHIKOYAT ANIQLANDI!</b>",
                "queue_overflow": "⏳ <b>KASSADA KATTA NAVBAT!</b>",
                "camera_offline": "🔌 <b>KAMERA ALOQASI UZILDI!</b>"
            }
            title = titles.get(alert_type, "⚠️ <b>OGOHLANTIRISH</b>")
            return (
                f"{title}\n"
                f"📹 <b>Kamera:</b> {camera_name}\n"
                f"ℹ️ <b>Sabab:</b> {message}\n\n"
                f"<i>Darhol choralar ko'rish tavsiya etiladi.</i>"
            )
        else:
            titles = {
                "employee_alert": "⚠️ <b>ПРЕДУПРЕЖДЕНИЕ: ПОВЕДЕНИЕ СОТРУДНИКА</b>",
                "complaint": "🚨 <b>ОБНАРУЖЕНА ЖАЛОБА КЛИЕНТА!</b>",
                "queue_overflow": "⏳ <b>БОЛЬШАЯ ОЧЕРЕДЬ НА КАССЕ!</b>",
                "camera_offline": "🔌 <b>ПОТЕРЯ СВЯЗИ С КАМЕРОЙ!</b>"
            }
            title = titles.get(alert_type, "⚠️ <b>ОПОВЕЩЕНИЕ</b>")
            return (
                f"{title}\n"
                f"📹 <b>Камера:</b> {camera_name}\n"
                f"ℹ️ <b>Детали:</b> {message}\n\n"
                f"<i>Рекомендуется проверить ситуацию на точке.</i>"
            )

    @staticmethod
    def format_camera_analysis_result(data: Dict[str, Any], language: str = "ru") -> str:
        """Formats the result of an instant frame/video/audio analysis in Telegram chat"""
        people = data.get("people_count", 0)
        entries = data.get("entries_detected", 0)
        purchases = data.get("purchases_detected", 0)
        queue = data.get("queue_length", 0)
        emp = data.get("employee_analysis", {})
        emp_status = emp.get("status", "active")
        emp_score = emp.get("behavior_score", 5.0)
        emp_alert = emp.get("alert_reason")
        desc = data.get("scene_description", "")

        if language == "uz":
            status_map = {
                "active": "✅ Ish joyida, faol",
                "idle": "💤 Harakatsiz kutmoqda",
                "on_phone": "📱 Telefonga chalg'igan!",
                "absent": "❌ Ish joyida yo'q!"
            }
            status_text = status_map.get(emp_status, emp_status)
            res = (
                f"🔍 <b>AI KADR TAHLILI NATIJASI</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👥 <b>Kadrda odamlar:</b> {people}\n"
                f"🚪 <b>Kirdi / Chiqdi:</b> +{entries} / -{data.get('exits_detected', 0)}\n"
                f"🛍 <b>Xarid qilmoqda:</b> {purchases}\n"
                f"⏳ <b>Navbat uzunligi:</b> {queue} kishi\n\n"
                f"👔 <b>Xodim holati:</b> {status_text} (⭐ {emp_score}/5.0)\n"
            )
            if emp_alert:
                res += f"⚠️ <i>Eslatma: {emp_alert}</i>\n"
            if desc:
                res += f"\n📝 <i>{desc}</i>"
            return res
        else:
            status_map = {
                "active": "✅ На месте, активно работает",
                "idle": "💤 Бездействует",
                "on_phone": "📱 Отвлекается в телефон!",
                "absent": "❌ Отсутствует на рабочем месте!"
            }
            status_text = status_map.get(emp_status, emp_status)
            res = (
                f"🔍 <b>РЕЗУЛЬТАТ AI-АНАЛИЗА КАДРА</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👥 <b>Людей в кадре:</b> {people}\n"
                f"🚪 <b>Вошло / Вышло:</b> +{entries} / -{data.get('exits_detected', 0)}\n"
                f"🛍 <b>Покупок на кассе:</b> {purchases}\n"
                f"⏳ <b>Длина очереди:</b> {queue} чел.\n\n"
                f"👔 <b>Поведение сотрудника:</b> {status_text} (⭐ {emp_score}/5.0)\n"
            )
            if emp_alert:
                res += f"⚠️ <i>Замечание: {emp_alert}</i>\n"
            if desc:
                res += f"\n📝 <i>{desc}</i>"
            return res
