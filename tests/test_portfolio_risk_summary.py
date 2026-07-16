"""Private portfolio risk brief tests."""

from src.management import portfolio_risk_summary
from src.runners import run_position_check


def _snapshot():
    return {
        "position_source": "actions_secret",
        "total_estimated_value": 10_000.0,
        "stocks": [
            {
                "symbol": "AAA",
                "shares": 100,
            }
        ],
        "options": [
            {
                "symbol": "AAA",
                "type": "long_call",
                "strike": 8,
                "expiry": "2027-12-17",
                "contracts": 1,
                "cost_per_contract": 300,
                "thesis_id": "ai_capex",
            },
            {
                "symbol": "BBB",
                "type": "short_call",
                "strike": 18,
                "expiry": "2027-12-17",
                "contracts": 1,
                "thesis_id": "ai_capex",
            },
        ],
    }


def test_private_portfolio_risk_calculates_greeks_and_concentration(monkeypatch):
    prices = {"AAA": 10.0, "BBB": 20.0}
    monkeypatch.setattr(
        portfolio_risk_summary,
        "get_latest_price",
        lambda symbol: prices[symbol],
    )
    monkeypatch.setattr(portfolio_risk_summary, "get_atm_iv", lambda symbol: 0.3)
    monkeypatch.setattr(
        portfolio_risk_summary,
        "calc_all_greeks",
        lambda **kwargs: {
            "delta": 0.8,
            "gamma": 0.01,
            "theta": -0.1,
            "vega": 0.2,
        },
    )
    monkeypatch.setattr(
        portfolio_risk_summary, "calc_bs_price", lambda **kwargs: 3.0
    )
    monkeypatch.setattr(
        portfolio_risk_summary,
        "read_json",
        lambda *args, **kwargs: {
            "themes": [{"id": "ai_capex"}],
            "symbols": [
                {"symbol": "AAA", "theme": "ai_capex"},
                {"symbol": "BBB", "theme": "ai_capex"},
            ],
        },
    )

    result = portfolio_risk_summary.analyze_private_portfolio(_snapshot())

    # AAA stock 1000 + AAA long-call delta 800 - BBB short-call delta 1600
    assert result["net_delta_notional"] == 200.0
    assert result["gross_delta_notional"] == 3400.0
    assert result["theta_per_day"] == 0.0
    assert result["vega_per_1pct"] == 0.0
    assert result["explicit_thesis_links"] == 2
    assert abs(result["thesis_coverage_pct"] - (2 / 3)) < 0.001
    assert result["symbol_exposure"][0]["symbol"] in {"AAA", "BBB"}


def test_private_portfolio_brief_contains_decision_metrics(monkeypatch):
    monkeypatch.setattr(
        portfolio_risk_summary,
        "get_latest_price",
        lambda symbol: 10.0,
    )
    monkeypatch.setattr(portfolio_risk_summary, "get_atm_iv", lambda symbol: 0.3)
    monkeypatch.setattr(
        portfolio_risk_summary,
        "calc_all_greeks",
        lambda **kwargs: {
            "delta": 0.8,
            "gamma": 0.01,
            "theta": -0.1,
            "vega": 0.2,
        },
    )
    monkeypatch.setattr(
        portfolio_risk_summary, "calc_bs_price", lambda **kwargs: 3.0
    )
    monkeypatch.setattr(
        portfolio_risk_summary,
        "read_json",
        lambda *args, **kwargs: {
            "themes": [{"id": "ai_capex"}],
            "symbols": [],
        },
    )

    summary = portfolio_risk_summary.analyze_private_portfolio(_snapshot())
    message = portfolio_risk_summary.format_private_portfolio_brief(summary)

    assert "淨 Delta" in message
    assert "每日 Theta" in message
    assert "Vega" in message
    assert "thesis" in message
    assert "不產生自動下單" in message


def test_runner_sends_private_brief_as_silent_sensitive(monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(
        run_position_check,
        "analyze_private_portfolio",
        lambda value: {"configured": True},
    )
    monkeypatch.setattr(
        run_position_check,
        "format_private_portfolio_brief",
        lambda value: "PRIVATE MESSAGE",
    )
    calls = []
    monkeypatch.setattr(
        run_position_check,
        "send_telegram",
        lambda message, **kwargs: calls.append((message, kwargs)) or True,
    )

    assert run_position_check._send_private_risk_brief(snapshot) is True
    assert calls == [
        (
            "PRIVATE MESSAGE",
            {
                "parse_mode": "HTML",
                "disable_notification": True,
                "sensitive": True,
            },
        )
    ]
