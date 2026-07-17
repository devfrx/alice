"""AL\\CE — Modelli dati dell'eval harness (scenari, esiti, report)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CheckKind = Literal[
    "file_exists",
    "file_absent",
    "file_contains",
    "response_matches",
    "tool_called",
    "tool_not_called",
    "max_steps",
    "finished_ok",
]

Domain = Literal[
    "filesystem",
    "search",
    "multistep",
    "planning",
    "permissions",
    "recovery",
    "knowledge",
]


class SandboxFile(BaseModel):
    """Un file da creare nella sandbox prima del turno."""

    model_config = ConfigDict(extra="forbid")

    path: str
    content: str = ""


class ScenarioSetup(BaseModel):
    """Preparazione dell'ambiente per uno scenario."""

    model_config = ConfigDict(extra="forbid")

    sandbox: list[SandboxFile] = Field(default_factory=list)
    permission_mode: str = "auto_edits"


class BudgetSpec(BaseModel):
    """Budget wall-clock dello scenario."""

    model_config = ConfigDict(extra="forbid")

    max_seconds: float = Field(default=180.0, gt=0)


class CheckSpec(BaseModel):
    """Un check deterministico. I campi usati dipendono da ``kind``."""

    model_config = ConfigDict(extra="forbid")

    kind: CheckKind
    path: str | None = None
    text: str | None = None
    pattern: str | None = None
    name: str | None = None
    value: int | None = None


class JudgeSpec(BaseModel):
    """Criteri qualitativi valutati dal judge LLM (misura secondaria)."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[str] = Field(min_length=1)


class Scenario(BaseModel):
    """Uno scenario agentico completo (un file YAML)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str
    domain: Domain
    setup: ScenarioSetup = Field(default_factory=ScenarioSetup)
    prompt: str = Field(min_length=1)
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    checks: list[CheckSpec] = Field(min_length=1)
    judge: JudgeSpec | None = None


class CheckResult(BaseModel):
    """Esito di un singolo check."""

    kind: CheckKind
    passed: bool
    detail: str = ""


class JudgeVerdict(BaseModel):
    """Verdetto del judge su un criterio (0-10)."""

    criterion: str
    score: int = Field(ge=0, le=10)
    reason: str = ""


class TraceSummary(BaseModel):
    """Sintesi numerica della trace di un turno."""

    steps: int = 0
    tool_calls: list[str] = Field(default_factory=list)
    finish_reason: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


class ScenarioResult(BaseModel):
    """Esito completo di uno scenario."""

    scenario_id: str
    domain: Domain
    passed: bool
    checks: list[CheckResult] = Field(default_factory=list)
    judge: list[JudgeVerdict] = Field(default_factory=list)
    trace: TraceSummary = Field(default_factory=TraceSummary)
    response: str = ""
    duration_seconds: float = 0.0
    error: str | None = None


class RunReport(BaseModel):
    """Report aggregato di un run della suite."""

    run_id: str
    model: str
    started_at: str
    scenarios: list[ScenarioResult] = Field(default_factory=list)
