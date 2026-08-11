"""Scripted Model/ModelSession fake that exercises the real ThinHarness loop."""

from dataclasses import dataclass

from thinharness import ModelCapabilities, ModelTurn


@dataclass
class ScriptedProvider:
    name: str = "Anthropic"
    api_key: str | None = "test-key"


class ScriptedModel:
    """One script per new ThinHarness session; each item is a turn or exception."""

    capabilities = ModelCapabilities(
        supports_json_schema_output=True,
        default_structured_output_mode="native",
    )

    def __init__(self, *session_scripts):
        self.model = "scripted-model"
        self.provider = ScriptedProvider()
        self.api_key = self.provider.api_key
        self._session_scripts = [list(script) for script in session_scripts]
        self.sessions = []
        self.events = []

    def new_session(self):
        if not self._session_scripts:
            raise AssertionError("No scripted session remains")
        session = ScriptedSession(self, self._session_scripts.pop(0))
        self.sessions.append(session)
        return session


class ScriptedSession:
    def __init__(self, model, script):
        self.model = model
        self.script = script

    async def start(self, prompt, constants, *, previous_response_id=None, notices=None):
        self.model.events.append(("start", prompt, constants))
        return self._next()

    async def continue_with_tools(self, outputs, constants, *, notices=None):
        self.model.events.append(("tools", outputs, constants))
        return self._next()

    async def continue_with_user_text(self, text, constants, *, notices=None):
        self.model.events.append(("user_text", text, constants))
        return self._next()

    def dump_state(self):
        return None

    def _next(self):
        if not self.script:
            raise AssertionError("Scripted session exhausted before run completed")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, ModelTurn):
            raise TypeError(f"Expected ModelTurn or exception, got {type(item).__name__}")
        return item
