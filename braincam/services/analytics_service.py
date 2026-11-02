from datetime import datetime, timezone, date
from typing import Dict, Any, Optional, List
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from braincam.db.models import (
    Organization, Camera, CameraEvent, DailyReport, Alert, EventTypeEnum
)
from braincam.ai.gemini_service import gemini_service

class AnalyticsService:
    """
    Computes retail KPI metrics:
      - Total Visitors (Footfall / Entries)
      - Total Purchases (Transactions at Checkout)
      - Conversion Rate: (Purchases / Visitors) * 100%
      - Peak Traffic Hours
      - Employee Attentiveness & Quality Score
      - Customer Audio Complaints & Actionable AI Recommendations
    """

    @staticmethod
    async def record_event(
        session: AsyncSession,
        org_id: int,
        camera_id: int,
        event_type: str,
        count: int = 1,
        details: Optional[Dict[str, Any]] = None
    ) -> CameraEvent:
        """Records an individual analytics event from camera AI pipeline"""
        event = CameraEvent(
            org_id=org_id,
            camera_id=camera_id,
            event_type=event_type,
            count=count,
            details=details or {},
            timestamp=datetime.now(timezone.utc)
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    @staticmethod
    async def get_daily_metrics(session: AsyncSession, org_id: int, target_date: Optional[str] = None) -> Dict[str, Any]:
        """Calculates real-time metrics for today or target date (YYYY-MM-DD)"""
        today_str = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Query all events for this organization today
        # Note: In SQLite/Postgres we filter by timestamp date
        stmt = select(CameraEvent).where(
            CameraEvent.org_id == org_id
        )
        result = await session.execute(stmt)
        events = result.scalars().all()

        # Filter events matching the target date
        day_events = [e for e in events if e.timestamp.strftime("%Y-%m-%d") == today_str]

        visitors = 0
        exits = 0
        purchases = 0
        complaints = 0
        employee_scores = []
        hourly_counts = {f"{h:02d}:00": 0 for h in range(8, 23)}

        for ev in day_events:
            hour_str = f"{ev.timestamp.hour:02d}:00"
            if ev.event_type == EventTypeEnum.ENTRY.value:
                visitors += ev.count
                if hour_str in hourly_counts:
                    hourly_counts[hour_str] += ev.count
            elif ev.event_type == EventTypeEnum.EXIT.value:
                exits += ev.count
            elif ev.event_type == EventTypeEnum.PURCHASE.value:
                purchases += ev.count
            elif ev.event_type == EventTypeEnum.COMPLAINT.value:
                complaints += ev.count
            elif ev.event_type == EventTypeEnum.EMPLOYEE_ALERT.value:
                score = (ev.details or {}).get("behavior_score")
                if score is not None:
                    employee_scores.append(float(score))

        # Peak traffic hour
        peak_hour = max(hourly_counts, key=hourly_counts.get) if any(hourly_counts.values()) else "18:00 - 19:00"

        # Calculate conversion rate
        conversion_rate = (purchases / visitors * 100.0) if visitors > 0 else 0.0

        # Calculate average staff behavior score
        avg_score = round(sum(employee_scores) / len(employee_scores), 1) if employee_scores else 4.9

        return {
            "date": today_str,
            "visitors_count": visitors,
            "exits_count": exits,
            "buyers_count": purchases,
            "conversion_rate": round(conversion_rate, 1),
            "peak_hour": f"{peak_hour} - {int(peak_hour[:2])+1:02d}:00",
            "complaints_count": complaints,
            "employee_score": avg_score,
            "hourly_traffic": hourly_counts
        }

    @staticmethod
    async def generate_or_update_daily_report(session: AsyncSession, org_id: int) -> DailyReport:
        """
        Generates and saves the final daily report with Gemini AI insights for the merchant.
        """
        metrics = await AnalyticsService.get_daily_metrics(session, org_id)
        today_str = metrics["date"]

        # Fetch organization language
        org_stmt = select(Organization).where(Organization.id == org_id)
        org_res = await session.execute(org_stmt)
        org = org_res.scalar_one_or_none()
        language = org.language if org else "ru"

        # Check existing report
        rep_stmt = select(DailyReport).where(
            and_(DailyReport.org_id == org_id, DailyReport.date == today_str)
        )
        rep_res = await session.execute(rep_stmt)
        report = rep_res.scalar_one_or_none()

        # Ask Gemini for intelligent retail tips and summary
        ai_digest = await gemini_service.generate_daily_merchant_digest(metrics, language=language)

        if not report:
            report = DailyReport(
                org_id=org_id,
                date=today_str,
                visitors_count=metrics["visitors_count"],
                buyers_count=metrics["buyers_count"],
                conversion_rate=metrics["conversion_rate"],
                peak_hour=metrics["peak_hour"],
                employee_score=metrics["employee_score"],
                employee_notes=ai_digest.get("employee_feedback", ""),
                complaints_count=metrics["complaints_count"],
                ai_recommendations="\n".join(f"• {r}" for r in ai_digest.get("recommendations", [])),
                sent_to_telegram=False
            )
            session.add(report)
        else:
            report.visitors_count = metrics["visitors_count"]
            report.buyers_count = metrics["buyers_count"]
            report.conversion_rate = metrics["conversion_rate"]
            report.peak_hour = metrics["peak_hour"]
            report.employee_score = metrics["employee_score"]
            report.employee_notes = ai_digest.get("employee_feedback", "")
            report.complaints_count = metrics["complaints_count"]
            report.ai_recommendations = "\n".join(f"• {r}" for r in ai_digest.get("recommendations", []))

        await session.commit()
        await session.refresh(report)
        return report
