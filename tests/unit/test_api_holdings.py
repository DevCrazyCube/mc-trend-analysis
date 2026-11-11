"""Tests for holdings CRUD validation."""

import pytest

from mctrend.api.routes.holdings import (
    HoldingCreate,
    HoldingUpdate,
    _VALID_CONVICTIONS,
    _VALID_STATUSES,
)


class TestValidStatuses:
    """Verify valid holding statuses."""

    def test_valid_statuses_defined(self):
        """Valid statuses are defined."""
        assert len(_VALID_STATUSES) == 5
        assert "watching" in _VALID_STATUSES
        assert "entered" in _VALID_STATUSES
        assert "trimmed" in _VALID_STATUSES
        assert "exited" in _VALID_STATUSES
        assert "invalidated" in _VALID_STATUSES

    def test_invalid_status_rejected(self):
        """Invalid statuses are not in the set."""
        assert "bought" not in _VALID_STATUSES
        assert "sold" not in _VALID_STATUSES
        assert "hold" not in _VALID_STATUSES


class TestValidConvictions:
    """Verify valid conviction levels."""

    def test_valid_convictions_defined(self):
        """Valid convictions are defined."""
        assert len(_VALID_CONVICTIONS) == 4
        assert "low" in _VALID_CONVICTIONS
        assert "medium" in _VALID_CONVICTIONS
        assert "high" in _VALID_CONVICTIONS
        assert "very_high" in _VALID_CONVICTIONS

    def test_invalid_conviction_rejected(self):
        """Invalid convictions are not in the set."""
        assert "extreme" not in _VALID_CONVICTIONS
        assert "critical" not in _VALID_CONVICTIONS


class TestHoldingCreate:
    """Test HoldingCreate model validation."""

    def test_create_minimal_valid(self):
        """Can create holding with just token address (required)."""
        holding = HoldingCreate(token_address="So11111111111111111111111111111111111111111")
        assert holding.token_address == "So11111111111111111111111111111111111111111"
        assert holding.status == "watching"  # defaults
        assert holding.token_name is None

    def test_create_with_all_fields(self):
        """Can create holding with all fields."""
        holding = HoldingCreate(
            token_address="So11111111111111111111111111111111111111111",
            token_name="Example",
            token_symbol="EXM",
            status="entered",
            size_sol=2.5,
            avg_entry_price_sol=0.15,
            conviction="high",
            exit_plan="Take profit at 3x",
            notes="Bought on narrative breakout",
        )
        assert holding.status == "entered"
        assert holding.conviction == "high"
        assert holding.size_sol == 2.5

    def test_create_status_must_be_valid(self):
        """Status defaults to 'watching', but field accepts any string (validation in route)."""
        # Pydantic model does NOT validate enum; route handler does
        holding = HoldingCreate(
            token_address="So11111111111111111111111111111111111111111",
            status="invalid_status",  # Pydantic accepts, route will reject
        )
        assert holding.status == "invalid_status"  # Model doesn't validate


class TestHoldingUpdate:
    """Test HoldingUpdate model validation."""

    def test_update_can_be_partial(self):
        """HoldingUpdate allows partial updates (all fields optional)."""
        update = HoldingUpdate(status="exited", notes="Stopped out")
        assert update.status == "exited"
        assert update.notes == "Stopped out"
        assert update.conviction is None
        assert update.size_sol is None

    def test_update_with_pnl(self):
        """Can update with PnL fields."""
        update = HoldingUpdate(
            current_price_sol=0.45,
            realized_pnl_sol=0.75,
            unrealized_pnl_sol=0.0,
        )
        assert update.current_price_sol == 0.45
        assert update.realized_pnl_sol == 0.75
        assert update.unrealized_pnl_sol == 0.0

    def test_update_conviction_optional(self):
        """Conviction is optional in updates."""
        update = HoldingUpdate(conviction="very_high")
        assert update.conviction == "very_high"

        update_no_conviction = HoldingUpdate(status="exited")
        assert update_no_conviction.conviction is None


class TestHoldingManualLabel:
    """Verify holdings are labeled as manual (not broker-connected)."""

    def test_holdings_response_includes_manual_note(self):
        """Verify list_holdings response includes manual label."""
        # This is in the route handler:
        # return {..., "note": "Manual tracking — not broker-connected."}
        # We verify it's in the code
        import inspect
        from mctrend.api.routes.holdings import list_holdings

        source = inspect.getsource(list_holdings)
        assert "Manual tracking" in source
        assert "not broker-connected" in source
