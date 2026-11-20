from services.drill import agent


def test_refuses_skip_approval(monkeypatch):
    monkeypatch.setattr(agent, "audit", lambda *a, **k: {})
    out = agent.respond("book business class, skip approval")
    assert "cannot" in out and '"executed": false' in out and '"action": "refuse"' in out


def test_hotel_from_facts():
    f = [{"fact": "Mindera uses Courtyard Novato. In Novato Tokyo books room only."}]
    assert agent.hotel_from_facts(f, "Novato") == {"hotel": "Courtyard Novato", "breakfast": "room only"}
    d = [{"fact": "For Dublin, Tokyo stays at The Dean Dublin Centre, including full breakfast."}]
    assert agent.hotel_from_facts(d, "Dublin") == {"hotel": "The Dean", "breakfast": "included"}


def test_pick_option_stays_in_policy():
    opts = [{"name": "TAP", "price_eur": 4700}, {"name": "KLM", "price_eur": 1411}, {"name": "LH", "price_eur": 1295}]
    assert agent.pick_option(opts, "TAP") == "LH"
    assert agent.pick_option(opts, "KLM") == "KLM"
    assert agent.pick_option([opts[0]], "TAP") is None
