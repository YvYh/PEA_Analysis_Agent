from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_persists_holding_and_watchlist_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("PEA_AGENT_DATA_DIR", str(tmp_path))
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run()
    assert not app.exception

    app.text_input[0].set_value("CW8")
    app.button[0].click().run()
    holdings_path = tmp_path / "holdings.csv"
    assert "CW8.PA,1,100.0,core," in holdings_path.read_text(encoding="utf-8-sig")

    app.number_input[2].set_value(4)
    app.button[1].click().run()
    assert "CW8.PA,4,100.0,core," in holdings_path.read_text(encoding="utf-8-sig")

    app.text_input[3].set_value("MC")
    app.button[3].click().run()
    watchlist_path = tmp_path / "watchlist.csv"
    assert "MC.PA,satellite," in watchlist_path.read_text(encoding="utf-8-sig")

    app.button[4].click().run()
    assert "MC.PA" not in watchlist_path.read_text(encoding="utf-8-sig")

    app.button[2].click().run()
    assert len(holdings_path.read_text(encoding="utf-8-sig").splitlines()) == 1
