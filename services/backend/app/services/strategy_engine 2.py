"""
Strategy evaluation engine.
Evaluates conditions and returns matching actions.
"""
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger("rsend.strategy")


class StrategyEvaluator:
    """Evaluates strategies against incoming transactions."""

    def evaluate_conditions(
        self,
        conditions: list[dict],
        context: dict,  # {amount, token, chain_id, chain_family, sender, gas_price, ...}
    ) -> bool:
        """All conditions must match (AND logic)."""
        for cond in conditions:
            if not self._check_condition(cond, context):
                return False
        return True

    def _check_condition(self, cond: dict, ctx: dict) -> bool:
        t = cond.get("type")
        v = cond.get("value")

        if t == "amount_gt":
            return float(ctx.get("amount", 0)) > float(v)
        elif t == "amount_lt":
            return float(ctx.get("amount", 0)) < float(v)
        elif t == "amount_between":
            amt = float(ctx.get("amount", 0))
            return float(cond["min"]) <= amt <= float(cond["max"])
        elif t == "token_is":
            return ctx.get("token", "").upper() == str(v).upper()
        elif t == "token_in":
            return ctx.get("token", "").upper() in [x.upper() for x in v]
        elif t == "token_not":
            return ctx.get("token", "").upper() != str(v).upper()
        elif t == "chain_is":
            return str(ctx.get("chain_id")) == str(v)
        elif t == "chain_family_is":
            return ctx.get("chain_family") == v
        elif t == "gas_below":
            return float(ctx.get("gas_price", 0)) < float(v)
        elif t == "gas_above":
            return float(ctx.get("gas_price", 0)) > float(v)
        elif t == "sender_is":
            return ctx.get("sender", "").lower() == str(v).lower()
        elif t == "sender_in":
            return ctx.get("sender", "").lower() in [x.lower() for x in v]
        elif t == "time_between":
            now = datetime.now(timezone.utc)
            start = datetime.strptime(cond["from"], "%H:%M").replace(
                year=now.year, month=now.month, day=now.day, tzinfo=timezone.utc
            )
            end = datetime.strptime(cond["to"], "%H:%M").replace(
                year=now.year, month=now.month, day=now.day, tzinfo=timezone.utc
            )
            return start <= now <= end
        elif t == "day_of_week":
            return datetime.now(timezone.utc).strftime("%A").lower() in [
                d.lower() for d in v
            ]
        elif t == "daily_count_lt":
            return int(ctx.get("daily_count", 0)) < int(v)
        elif t == "daily_volume_lt":
            return float(ctx.get("daily_volume", 0)) < float(v)
        else:
            logger.warning(f"Unknown condition type: {t}")
            return True  # Unknown conditions pass (fail-open for forward compat)

    def find_matching_strategies(
        self,
        strategies: list,  # list of Strategy ORM objects
        context: dict,
    ) -> list:
        """Return all strategies whose conditions match, sorted by priority."""
        matches = []
        for strategy in strategies:
            if not strategy.is_active:
                continue
            if strategy.expires_at and strategy.expires_at < datetime.utcnow():
                continue
            if self.evaluate_conditions(strategy.conditions, context):
                matches.append(strategy)

        # Sort by priority (highest first)
        return sorted(matches, key=lambda s: s.priority, reverse=True)
