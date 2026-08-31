from sqlalchemy import Column, String, DateTime, Float, Integer, ForeignKey
from datetime import datetime, timezone
from db.session import Base
import uuid


class User(Base):
    __tablename__ = "users"


    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    thread_id = Column(String, nullable=False, index=True)
    query = Column(String, nullable=False)
    final_report = Column(String, nullable=True)
    quality_score = Column(Float, nullable=True)
    retry_count = Column(Integer, default=0)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


