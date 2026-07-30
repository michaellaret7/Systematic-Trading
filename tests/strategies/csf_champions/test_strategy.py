"""CSF Champions broker lifecycle hooks."""

from systematic_trading.strategies.csf_champions.strategy import CsfChampions


class InitializeContext:
    """Minimal strategy state required by ``initialize``."""

    parameters = {
        "generate_ideas": False,
        "build_portfolio": False,
    }


class IterationContext:
    """Minimal strategy state required by ``on_trading_iteration``."""


def test_initialize_sets_daily_cadence() -> None:
    """Initialization configures Lumibot to iterate once per trading day."""
    context = InitializeContext()

    CsfChampions.initialize(context)

    assert context.sleeptime == "1D"


def test_trading_iteration_logs_daily_heartbeat(monkeypatch) -> None:
    """The daily iteration remains active without side-effect bookkeeping."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    messages: list[str] = []
    monkeypatch.setattr(strategy_module.log, "info", lambda message, *a: messages.append(message))

    CsfChampions.on_trading_iteration(IterationContext())

    assert messages == ["CSF Champions daily trading iteration"]
