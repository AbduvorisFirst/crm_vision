from datetime import datetime, timezone, timedelta
import enum
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class LanguageEnum(str, enum.Enum):
    RU = "ru"
    UZ = "uz"

class UserStatusEnum(str, enum.Enum):
    PENDING = "pending"     # Ждет одобрения администратора @abdvoris07
    ACTIVE = "active"       # Одобрен, действует пробный период или оплата
    REJECTED = "rejected"   # Отклонен
    EXPIRED = "expired"     # Срок триала/подписки истек

class CameraTypeEnum(str, enum.Enum):
    ENTRANCE = "entrance"    # Детекция входа/выхода (трафик)
    CHECKOUT = "checkout"    # Кассовая зона (покупки, конверсия, поведение кассира)
    HALL = "hall"            # Торговый зал (поведение сотрудников, скопления)
    OUTDOOR = "outdoor"      # Вход снаружи / витрина

class CameraStatusEnum(str, enum.Enum):
    ONLINE = "online"
    PROCESSING = "processing"
    OFFLINE = "offline"
    ERROR = "error"
    PAUSED = "paused"

class EventTypeEnum(str, enum.Enum):
    ENTRY = "entry"                   # Вошел посетитель
    EXIT = "exit"                     # Вышел посетитель
    PURCHASE = "purchase"             # Совершена покупка
    EMPLOYEE_ALERT = "employee_alert" # Замечание по сотруднику
    COMPLAINT = "complaint"           # Голосовая жалоба покупателя
    QUEUE_OVERFLOW = "queue_overflow" # Очередь на кассе

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    owner_telegram_id = Column(Integer, index=True, nullable=True)
    language = Column(String(5), default="ru")  # "ru" or "uz"
    timezone = Column(String(50), default="Asia/Tashkent")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    locations = relationship("Location", back_populates="organization", cascade="all, delete-orphan")
    cameras = relationship("Camera", back_populates="organization", cascade="all, delete-orphan")
    daily_reports = relationship("DailyReport", back_populates="organization", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String(100), nullable=True)
    full_name = Column(String(150), nullable=True)
    phone = Column(String(50), nullable=True)
    role = Column(String(20), default="merchant")  # owner, admin, merchant

    # Business profile
    store_name = Column(String(150), nullable=True)
    business_category = Column(String(100), nullable=True) # Супермаркет, Одежда, Кафе и т.д.
    city = Column(String(100), nullable=True)
    instagram = Column(String(100), nullable=True) # @instagram_shop
    camera_count = Column(Integer, default=1)

    # Status & 7-day Trial
    status = Column(String(20), default=UserStatusEnum.PENDING.value)
    trial_starts_at = Column(DateTime, nullable=True)
    trial_ends_at = Column(DateTime, nullable=True)
    is_paid = Column(Boolean, default=False)
    paid_until = Column(DateTime, nullable=True)
    reminders_sent = Column(Integer, default=0) # Сколько напоминаний об оплате отправлено (1, 2, 3)

    # Preferences
    language = Column(String(5), default="ru")  # "ru" or "uz"
    daily_report_time = Column(String(10), default="21:00") # Например, 20:00 или 22:00
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization", back_populates="users")
    payments = relationship("PaymentReceipt", back_populates="user", cascade="all, delete-orphan")

    def is_access_granted(self) -> bool:
        """Checks if merchant has active access (either approved trial or paid subscription)"""
        if self.status != UserStatusEnum.ACTIVE.value:
            return False
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        paid = (
            self.paid_until.astimezone(timezone.utc).replace(tzinfo=None)
            if (self.paid_until and self.paid_until.tzinfo)
            else (self.paid_until.replace(tzinfo=None) if self.paid_until else None)
        )
        trial = (
            self.trial_ends_at.astimezone(timezone.utc).replace(tzinfo=None)
            if (self.trial_ends_at and self.trial_ends_at.tzinfo)
            else (self.trial_ends_at.replace(tzinfo=None) if self.trial_ends_at else None)
        )
        if self.is_paid and paid and paid > now:
            return True
        if trial and trial > now:
            return True
        return False

    def days_left(self) -> int:
        """Returns days left in trial or subscription"""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        target = self.paid_until if self.is_paid else self.trial_ends_at
        if not target:
            return 0
        target_naive = (
            target.astimezone(timezone.utc).replace(tzinfo=None)
            if target.tzinfo
            else target.replace(tzinfo=None)
        )
        diff = target_naive - now
        return max(0, diff.days)

class PaymentReceipt(Base):
    __tablename__ = "payment_receipts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    telegram_file_id = Column(String(255), nullable=False)
    status = Column(String(20), default="pending") # pending, approved, rejected
    amount_info = Column(String(100), default="300 000 UZS / 25 USD")
    admin_notes = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="payments")

class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    name = Column(String(150), nullable=False)
    address = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization", back_populates="locations")
    cameras = relationship("Camera", back_populates="location")

class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    name = Column(String(100), nullable=False)
    rtsp_url = Column(String(255), nullable=False)
    camera_type = Column(String(20), default=CameraTypeEnum.ENTRANCE.value)
    has_audio = Column(Boolean, default=False)
    status = Column(String(20), default=CameraStatusEnum.ONLINE.value)
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    fps = Column(Float, default=5.0)
    config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization", back_populates="cameras")
    location = relationship("Location", back_populates="cameras")
    events = relationship("CameraEvent", back_populates="camera", cascade="all, delete-orphan")

class CameraEvent(Base):
    __tablename__ = "camera_events"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    event_type = Column(String(30), nullable=False)
    count = Column(Integer, default=1)
    confidence = Column(Float, default=1.0)
    details = Column(JSON, default=dict)

    camera = relationship("Camera", back_populates="events")

class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    date = Column(String(10), nullable=False, index=True)
    visitors_count = Column(Integer, default=0)
    buyers_count = Column(Integer, default=0)
    conversion_rate = Column(Float, default=0.0)
    peak_hour = Column(String(20), default="18:00 - 19:00")
    employee_score = Column(Float, default=5.0)
    employee_notes = Column(Text, nullable=True)
    complaints_count = Column(Integer, default=0)
    ai_recommendations = Column(Text, nullable=True)
    sent_to_telegram = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization", back_populates="daily_reports")

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), default="warning")
    message = Column(Text, nullable=False)
    is_resolved = Column(Boolean, default=False)
    sent_to_telegram = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
