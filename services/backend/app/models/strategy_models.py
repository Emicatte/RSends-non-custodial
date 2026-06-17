"""
Strategy models — conditional automation rules.

A Strategy is a set of Conditions + Actions:
  IF conditions match THEN execute actions.
"""
from sqlalchemy import Column, Integer, String, Boolean, Float, JSON, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.db_models import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_address = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)  # Higher = evaluated first

    # Chain scope
    chain_family = Column(String, default="evm")  # evm, solana, tron, any
    chain_id = Column(String, nullable=True)  # null = all chains in family

    # Conditions (JSON array)
    # Each condition: {"type": "amount_gt", "value": "1.0", "token": "ETH"}
    conditions = Column(JSON, default=list)

    # Actions (JSON array)
    # Each action: {"type": "swap", "params": {"to_token": "USDC"}}
    actions = Column(JSON, default=list)

    # Execution limits
    max_executions_per_day = Column(Integer, nullable=True)
    cooldown_seconds = Column(Integer, default=60)
    expires_at = Column(DateTime, nullable=True)

    # Tracking
    total_executions = Column(Integer, default=0)
    last_executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ═══ Condition Types ═══
CONDITION_TYPES = {
    # Amount conditions
    "amount_gt":      "Incoming amount > threshold",
    "amount_lt":      "Incoming amount < threshold",
    "amount_between": "Incoming amount between min and max",

    # Token conditions
    "token_is":       "Incoming token is specific token",
    "token_in":       "Incoming token is one of list",
    "token_not":      "Incoming token is NOT specific token",

    # Chain conditions
    "chain_is":       "Source chain is specific chain",
    "chain_family_is":"Source chain family (evm/solana/tron)",

    # Time conditions
    "time_between":   "Current time between start and end (UTC)",
    "day_of_week":    "Current day is one of specified days",

    # Gas conditions
    "gas_below":      "Gas price below threshold (gwei)",
    "gas_above":      "Gas price above threshold (gwei)",

    # Sender conditions
    "sender_is":      "Sender is specific address",
    "sender_in":      "Sender is in whitelist",

    # Frequency conditions
    "daily_count_lt": "Daily execution count below limit",
    "daily_volume_lt":"Daily volume below limit",
}

# ═══ Action Types ═══
ACTION_TYPES = {
    # Transfer actions
    "forward":        "Forward to destination address",
    "split":          "Split between multiple addresses",

    # Swap actions
    "swap":           "Swap to target token before forwarding",
    "swap_if_better": "Swap only if rate is above threshold",

    # Timing actions
    "delay":          "Wait N seconds before executing",
    "delay_until_gas":"Wait until gas drops below threshold",
    "batch":          "Accumulate and batch-send every N minutes",

    # Notification actions
    "notify":         "Send notification (Telegram/email)",
    "webhook":        "Call external webhook URL",

    # Control actions
    "stop":           "Stop processing (emergency brake)",
    "log":            "Log event without action",
}
