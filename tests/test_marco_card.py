import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import marco_card as card  # noqa: E402

OPTIONS = {"trip": "Novato", "dates": "Mon 30 Nov – Fri 4 Dec", "hotel": "Hotel X, EUR 180/night",
           "hotel_source": "Perk", "policy": "Economy under 6 h (Travel Policy 3.2)", "options": [
               {"label": "A", "flights": "TP 237 · UA 990", "times": "10:00 → 17:30", "price": "EUR 1,411",
                "in_policy": True, "best": True, "note": "Star Alliance, earns Miles&Go"},
               {"label": "B", "flights": "LH 455", "times": "12:00 → 20:00", "price": "EUR 2,100", "in_policy": False}]}
REPLAN = {"trip": "Novato", "old_dates": "30 Nov – 4 Dec", "new_dates": "12 – 14 Jan",
          "actions": [{"kind": "calendar", "text": "Move blocks"}, {"kind": "uber", "text": "Re-reserve ride"}]}


def _text(blocks):
    return json.dumps(blocks, ensure_ascii=False)


def test_options_card_has_badges_best_tag_and_footer():
    b = card.options_blocks(OPTIONS)
    assert b[0]["type"] == "header" and "Novato" in b[0]["text"]["text"]
    t = _text(b)
    assert "✅ In policy" in t and "⚠️ Out of policy" in t
    assert t.count("Best value") == 1 and "Miles&Go" in t and "source: Perk" in t
    assert b[-1]["text"]["text"] == "Reply `@Marco approve A`."


def test_clash_card_puts_trips_side_by_side():
    b = card.clash_blocks({"existing": "Novato 30 Nov", "new": "Lisbon 1 Dec",
                           "options": [{"label": "A", "text": "Send someone else"}]})
    assert b[0]["text"]["text"] == "⚠️ Clash"
    assert len(b[1]["fields"]) == 2
    assert "• *A)* Send someone else" in _text(b) and "A`, `B` or `C" in _text(b)


def test_replan_card_numbers_actions_with_icons():
    t = _text(card.replan_blocks(REPLAN))
    assert "1. 📅 Move blocks" in t and "2. 🚕 Re-reserve ride" in t
    assert "Nothing changes until you approve." in t and "→" in t


def test_cancel_card_lists_free_cancel_notes():
    b = card.cancel_blocks({"traveller": "Tokyo", "actions": [{"kind": "perk", "text": "Delete draft"}],
                            "free_cancel": ["Uber free until 1 h before"]})
    assert b[0]["text"]["text"] == "🛑 Cancel trip for Tokyo"
    assert "1. ✈️ Delete draft" in _text(b) and "🆓 Uber free until 1 h before" in _text(b)


def test_every_card_has_a_fallback_text_and_valid_limits():
    for kind, facts in [("options", OPTIONS), ("replan", REPLAN)]:
        assert card.fallback_text(kind, facts)
        for blk in card.BUILDERS[kind](facts):
            assert len(blk.get("fields", [])) <= 10
