
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _persona_gate_on_in_tests(monkeypatch):
    """Tests assume the Persona gate is on, whatever the local .env says."""
    monkeypatch.setenv("MARCO_PERSONA_GATE", "on")
