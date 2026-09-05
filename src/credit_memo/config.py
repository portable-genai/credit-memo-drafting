"""Configuration and the adapter factory (dependency injection for the hexagon).

The factory reads ``config/settings.yaml`` (with ``${ENV_VAR}`` interpolation) and binds
each port to a concrete adapter by dotted path. Switching the whole system from the GCP
managed stack to an on-prem stack is a one-line change of ``profile`` (proof of the
ports-and-adapters / no-lock-in principle, P-02). Every adapter follows one construction
convention: ``Adapter(settings: Settings)``.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from .envread import (
    ConfiguredEmptyError,
    EnvSetting,
    optional_setting,
    read_env_setting,
    setting_or_default,
)

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")

_PROFILE_ENV = "CREDIT_MEMO_PROFILE"

#: Every profile that binds an adapter family. ``local`` is the SDK-free offline stack,
#: ``live`` adds real SEC EDGAR grounding plus a local model server, ``gcp`` and ``platform``
#: are the managed stacks, ``onprem`` is the fail-fast portability placeholder.
RUNTIME_PROFILES = frozenset({"gcp", "local", "live", "platform", "onprem"})

#: The profile string handed to every INTERNET-FACING relaxation when ``CREDIT_MEMO_PROFILE``
#: was never set. It is deliberately NOT a member of :data:`RUNTIME_PROFILES` and never reaches
#: :class:`Settings`: it exists so that "no choice was made" is a distinct input to the security
#: layers rather than being indistinguishable from a chosen ``local``.
UNCONSENTED_PROFILE = "unconfigured"


def _interpolate(value: Any) -> Any:
    """Replace ``${VAR}`` / ``${VAR:-default}`` tokens in strings recursively."""
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            return setting_or_default(m.group(1), m.group(2) or "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


def _validate_profile(profile: str) -> str:
    """Fail closed on a profile string nothing binds, INCLUDING a capitalisation typo.

    The comparison is exact and case-sensitive on purpose: every posture decision downstream
    matches the profile string exactly, so ``Local`` selects none of the relaxations but also
    none of the restrictions. Normalising the case here would turn a typo into a silent choice;
    refusing it turns the typo into a load failure.
    """
    if profile not in RUNTIME_PROFILES:
        expected = ", ".join(sorted(RUNTIME_PROFILES))
        raise ValueError(f"unknown {_PROFILE_ENV} {profile!r}; expected one of: {expected}")
    return profile


@dataclass(frozen=True)
class ProfileChoice:
    """The ONE resolution of ``CREDIT_MEMO_PROFILE``, and what each consumer must key off.

    Every module that needs the profile reads it from :class:`Settings` (which resolves it
    once, here). No module may re-derive the profile with its own
    ``os.environ.get("CREDIT_MEMO_PROFILE", "local")``: that fallback reads an UNSET variable
    as consent, which is the fail-open this type exists to remove
    (``tests/unit/test_profile_single_source.py`` fails the build if one reappears).

    The two derived profile strings differ because the two decisions fail closed in OPPOSITE
    directions, so a single "effective profile" string would harden one and weaken the other.
    """

    #: Which adapter family to bind. Absent consent this is still ``local`` (the SDK-free
    #: adapters), because the alternative would import cloud SDKs that are not installed; the
    #: local IDENTITY adapter refuses to construct when :attr:`explicit` is False, so an
    #: unconsented run has data adapters but no end-user identity.
    profile: str = "local"
    #: Was the profile named DELIBERATELY (``CREDIT_MEMO_PROFILE`` set, or a profile written
    #: into ``config/settings.yaml``)?
    explicit: bool = True

    @property
    def exposure_profile(self) -> str:
        """The profile every *relaxation* keys off: CORS origins and the dev-persona header.

        These decisions grant something extra to ``local``, so an unconsented run must NOT
        look like ``local``: it gets :data:`UNCONSENTED_PROFILE`, which is no origin's
        allowlist and no seeded persona.
        """
        return self.profile if self.explicit else UNCONSENTED_PROFILE

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off, where ``local`` is the RESTRICTIVE case.

        ``resolve_bind_host`` confines ``local`` to loopback and lets fronted profiles take
        ``0.0.0.0``, so here an unconsented run must look like ``local`` and stay on loopback.
        """
        return self.profile if self.explicit else "local"


def _profile_setting(environ: Mapping[str, str] | None) -> EnvSetting:
    if environ is None:
        return read_env_setting(_PROFILE_ENV)
    raw = environ.get(_PROFILE_ENV)
    return EnvSetting(name=_PROFILE_ENV, raw=raw, value="" if raw is None else raw.strip())


def resolve_profile(environ: Mapping[str, str] | None = None) -> ProfileChoice:
    """Read ``CREDIT_MEMO_PROFILE`` once: absent is NO CHOICE; empty refuses.

    A value that IS present is validated here, not later, so an unknown or mis-capitalised
    profile is a load failure rather than an app that has already chosen its CORS and bind
    postures from a string nothing binds.
    """
    setting = _profile_setting(environ)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{_PROFILE_ENV} is set to an empty value; unset it for the unconsented "
            "loopback-only posture, or name a supported profile."
        )
    if setting.is_unset:
        return ProfileChoice(profile="local", explicit=False)
    return ProfileChoice(profile=_validate_profile(setting.value), explicit=True)


#: The profiles whose runtime is a managed cloud, for :attr:`Settings.runtime`. ``live`` is
#: NOT one: since 2026-08-30 its models are the Gemini API, but the process, the index and
#: the audit trail are all on the operator's machine, and the banner states WHERE while the
#: model half states WHOSE. ``onprem`` is not one either.
_MANAGED_PROFILES: frozenset[str] = frozenset({"gcp", "platform"})


@dataclass(frozen=True)
class ModelSettings:
    #: The Vertex location the model client calls, NOT the compute region. Gemini 3
    #: serves the `us` and `eu` multi-regions only; `global` carries no residency
    #: guarantee. See models.location in config/settings.yaml.
    location: str = "us"
    reasoning: str = "gemini-3.5-flash"
    triage: str = "gemini-3.5-flash"
    hard_reasoning: str = "gemini-3.5-flash"  # Preview — feature-flagged off by default
    use_hard_reasoning: bool = False


@dataclass(frozen=True)
class KnowledgeBaseSettings:
    """Retrieval settings. There is no standing store to locate any more.

    Retrieval is an in-process index over the documents of the analysis being built,
    discarded with the container, so ``data_store_id`` and ``location`` are gone with the
    Agent Search adapter that needed them. ``base_url_env`` remains for a deployment that
    delegates retrieval to the shared knowledge platform instead.
    """

    base_url_env: str = "KNOWLEDGE_BASE_URL"
    top_k: int = 10


@dataclass(frozen=True)
class PeerDataSettings:
    dataset: str = "credit_peers"  # BigQuery dataset of peer financials
    table: str = "peer_financials"
    location: str = "asia-southeast1"
    max_peers: int = 25


@dataclass(frozen=True)
class ModelArmorSettings:
    template_id: str = "credit-memo-guardrail"
    host: str = "modelarmor.asia-southeast1.rep.googleapis.com"


@dataclass(frozen=True)
class DlpSettings:
    inspect_template: str = ""  # projects/.../inspectTemplates/...
    deidentify_template: str = ""  # projects/.../deidentifyTemplates/...


@dataclass(frozen=True)
class PiiSettings:
    """Which jurisdictions' national identifiers the redactor and the eval gate detect.

    Drives BOTH the local regex redactor and the GCP DLP custom info types from one pattern
    source (the shared ``pii-kit`` package), so a deployment outside APAC detects its own
    identifiers by editing this list rather than changing code. The supported packs live in
    ``pii_kit.patterns`` (``pii_kit.DEFAULT_JURISDICTIONS`` is its APAC reference default,
    which this mirrors); override at runtime with ``CREDIT_MEMO_PII_JURISDICTIONS``
    (comma-separated ISO-3166 alpha-2 codes). Unknown codes degrade safely to universal
    email/phone only.
    """

    jurisdictions: tuple[str, ...] = ("SG", "HK", "JP", "AU")


def _pii_settings(raw: Any) -> PiiSettings:
    """Build :class:`PiiSettings`, honouring the env override and normalising the codes.

    ``CREDIT_MEMO_PII_JURISDICTIONS`` (comma-separated) wins over the settings file so an
    operator can retarget the pack without editing YAML. Codes are upper-cased and coerced
    to a tuple: YAML yields a list, the env yields a string, and the frozen dataclass is
    compared by value, so the type must not depend on where the value came from.
    """
    data = dict(raw or {})
    env = optional_setting("CREDIT_MEMO_PII_JURISDICTIONS")
    if env is not None:
        codes_from_env = [code.strip() for code in env.split(",") if code.strip()]
        if not codes_from_env:
            raise ConfiguredEmptyError(
                "CREDIT_MEMO_PII_JURISDICTIONS is configured but names no jurisdiction"
            )
        data["jurisdictions"] = codes_from_env
    codes = data.get("jurisdictions")
    if codes is not None:
        if isinstance(codes, str):
            codes = codes.split(",")
        data["jurisdictions"] = tuple(str(c).strip().upper() for c in codes if str(c).strip())
    return PiiSettings(**data)


@dataclass(frozen=True)
class LoggingSettings:
    log_name: str = "credit-memo-audit"
    bucket: str = "credit-memo-worm"
    retention_days: int = 2557  # ~7 years


@dataclass(frozen=True)
class AgentEngineSettings:
    resource_name: str = ""  # reasoningEngine resource id, set after deploy
    display_name: str = "credit-memo-drafting"


@dataclass(frozen=True)
class PolicySettings:
    """Bank-owned deterministic underwriting policy, with reference defaults."""

    covenant_at_risk_band: float = 0.05

    def __post_init__(self) -> None:
        if not 0.0 <= self.covenant_at_risk_band <= 1.0:
            raise ValueError("policy.covenant_at_risk_band must be between 0 and 1")


@dataclass(frozen=True)
class LocalSettings:
    """Paths for the SDK-free ``local`` profile stores (SQLite FTS5 + append-only audit).

    Empty strings select the per-package default under ``~/.credit_memo/``; tests pass
    ``:memory:`` for ephemeral, deterministic stores. No Google Cloud here: the local
    profile runs the whole memo pipeline offline (SQLite FTS5 retrieval, a deterministic
    schema-driven LLM, regex DLP, a heuristic guardrail, an append-only audit store).
    """

    db_path: str = ""  # SQLite FTS5 borrower/policy index; "" => ~/.credit_memo/local.db
    audit_path: str = ""  # append-only audit store;          "" => ~/.credit_memo/audit.db


@dataclass(frozen=True)
class AnalysisBundleSettings:
    """Where one analysis lives, and for how long.

    ``retention_days`` is the promise the console prints to the user, so it is a single
    configured number rather than something each adapter decides. On the managed profiles
    the bucket's own lifecycle rule enforces it; the local adapter refuses an expired
    bundle on read and sweeps the disk.

    Fifteen days is the shipped default: long enough that a committee can reopen the
    evidence behind a memo it read last week, short enough that this service never
    becomes the bank's document store. Nothing here is a system of record.
    """

    bucket: str = ""  # regional CMEK bucket (gcp/platform); "" => not configured
    prefix: str = "analyses"
    root: str = ""  # local filesystem root; "" => ~/.credit_memo/analyses
    retention_days: int = 15
    max_upload_bytes: int = 20 * 1024 * 1024
    max_documents: int = 40


@dataclass(frozen=True)
class LiveSettings:
    """The ``live`` profile: real grounding on SEC EDGAR, generated by the Gemini API.

    The profile carries no model-server settings. Grounding comes from the SEC's public
    submissions / XBRL company-facts APIs (US-government public-domain data), fetched
    with the polite identified User-Agent the SEC requires and cached on disk so a demo
    never re-downloads the same filing data. EDGAR is not Google Search, but it leaves
    the data centre all the same, so a laptop generator beside it would be a local-model
    claim the use case cannot support (org decision, 2026-08-30). Requires
    GOOGLE_CLOUD_PROJECT + ADC.
    """

    max_output_tokens: int = 2048
    edgar_user_agent: str = "credit-memo-drafting-live/1.0"
    edgar_cache_dir: str = ""  # "" => ~/.credit_memo/edgar-cache
    edgar_cache_ttl_seconds: int = 24 * 3600  # 0 disables the on-disk cache
    peer_limit: int = 3  # peers per metric in the peer comparison


def _live_settings(raw: dict[str, Any]) -> LiveSettings:
    """Build LiveSettings with numeric coercion (env interpolation yields strings)."""
    for key, cast in (
        ("max_output_tokens", int),
        ("edgar_cache_ttl_seconds", int),
        ("peer_limit", int),
    ):
        if key in raw:
            raw[key] = cast(raw[key])
    return LiveSettings(**raw)


#: Multi-regions Document AI may use as a STATED residency deviation from the deploy region.
#: Each names one jurisdiction and carries an ML-processing commitment for it. `global` is
#: deliberately absent: it names no jurisdiction at all.


@dataclass(frozen=True)
class Settings:
    project_id: str = "your-gcp-project"
    region: str = "asia-southeast1"
    profile: str = "local"  # gcp | local | live | platform | onprem (local is the SDK-free default)
    kms_key: str = ""  # projects/.../cryptoKeys/... (regional)
    grounding_enabled: bool = False
    models: ModelSettings = field(default_factory=ModelSettings)
    knowledge_base: KnowledgeBaseSettings = field(default_factory=KnowledgeBaseSettings)
    peer_data: PeerDataSettings = field(default_factory=PeerDataSettings)
    model_armor: ModelArmorSettings = field(default_factory=ModelArmorSettings)
    dlp: DlpSettings = field(default_factory=DlpSettings)
    pii: PiiSettings = field(default_factory=PiiSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    agent_engine: AgentEngineSettings = field(default_factory=AgentEngineSettings)
    policy: PolicySettings = field(default_factory=PolicySettings)
    local: LocalSettings = field(default_factory=LocalSettings)
    analysis_bundle: AnalysisBundleSettings = field(default_factory=AnalysisBundleSettings)
    live: LiveSettings = field(default_factory=LiveSettings)
    # port_name -> { profile -> "module.path:ClassName" }
    adapters: dict[str, dict[str, str]] = field(default_factory=dict)
    # Was the profile chosen DELIBERATELY, or merely inherited from the fallback? ``load``
    # sets this False when neither CREDIT_MEMO_PROFILE nor the settings file names a profile.
    # Direct construction is deliberate by definition (a caller named the profile in code),
    # so the default is True. The seeded-persona identity adapter refuses to serve when this
    # is False: an underwriting assistant must never hand out a credit-approver persona
    # because an env var went missing.
    profile_explicit: bool = True

    def __post_init__(self) -> None:
        """The retention this deployment promises must be one the storage layer can keep.

        The Document AI residency check that used to live here is gone with the processor:
        text extraction is pypdf over the uploaded bytes, in-process, so there is no
        location left to validate. What replaced it guards the one number this deployment
        states to a user. A window Terraform will not enforce is a promise the console
        should not print, so an out-of-range value fails at load rather than at the moment
        somebody goes looking for evidence that was deleted early -- or never deleted.
        """
        retention = self.analysis_bundle.retention_days
        if not 1 <= retention <= 90:
            raise ValueError(
                f"analysis_bundle.retention_days {retention} must be between 1 and 90. It "
                "is the window the console promises the user, and infra/terraform enforces "
                "it as a bucket lifecycle rule (var.analysis_retention_days validates the "
                "same range). The two must agree."
            )

    @property
    def runtime(self) -> str:
        """Where this process is running, as the UI banner states it: ``gcp`` or ``local``.

        Derived from the profile, never sniffed from the environment. A console that read
        its runtime from ``window.location`` would be right until the deployment served
        through a proxy and wrong silently after that, so the service is the one asked.
        ``onprem`` reads ``local`` deliberately: it runs on the adopter's own iron, and
        "on GCP" is the one sentence that deployment must never print.
        """
        return "gcp" if self.profile in _MANAGED_PROFILES else "local"

    @property
    def generator_model(self) -> str:
        """Which model answers, for the UI banner (org decision, 2026-08-30).

        Read off the LLM binding the container will actually build, not from a second
        field someone has to remember to update. A repo that rebinds ``llm`` for a profile
        changes what the banner says in the same edit, which is the only way the two stay
        true to each other: a settings string would be a claim ABOUT the binding rather
        than the binding.
        """
        binding = self.adapters.get("llm", {}).get(self.profile, "")
        _, _, class_name = binding.partition(":")
        if class_name == "GeminiLLMAdapter":
            models = self.models
            return models.hard_reasoning if models.use_hard_reasoning else models.reasoning
        if class_name == "OnPremLLMAdapter":
            # The on-prem adapter is a fail-fast migration placeholder: it raises rather
            # than generating. Naming a model here would advertise one that never answers.
            return "onprem-not-implemented"
        return "deterministic-offline-stub"

    @property
    def profile_choice(self) -> ProfileChoice:
        """The resolved profile as the two-directional posture input the security layers use.

        Read ``exposure_profile`` for anything that GRANTS (CORS origins, dev personas) and
        ``bind_profile`` for anything that RESTRICTS (the loopback bind guard). Never compare
        ``profile`` directly for a posture decision: it cannot tell a chosen ``local`` from an
        inherited one.
        """
        return ProfileChoice(profile=self.profile, explicit=self.profile_explicit)

    @staticmethod
    def load(path: str | os.PathLike[str] | None = None) -> Settings:
        path = Path(path or setting_or_default("CREDIT_MEMO_SETTINGS", "config/settings.yaml"))
        raw = _interpolate(yaml.safe_load(path.read_text())) if path.exists() else {}
        raw = raw or {}
        nested: dict[str, Any] = {
            "models": ModelSettings(**(raw.pop("models", {}) or {})),
            "knowledge_base": KnowledgeBaseSettings(**(raw.pop("knowledge_base", {}) or {})),
            "peer_data": PeerDataSettings(**(raw.pop("peer_data", {}) or {})),
            "model_armor": ModelArmorSettings(**(raw.pop("model_armor", {}) or {})),
            "dlp": DlpSettings(**(raw.pop("dlp", {}) or {})),
            "pii": _pii_settings(raw.pop("pii", {})),
            "logging": LoggingSettings(**(raw.pop("logging", {}) or {})),
            "agent_engine": AgentEngineSettings(**(raw.pop("agent_engine", {}) or {})),
            "policy": PolicySettings(**(raw.pop("policy", {}) or {})),
            "local": LocalSettings(**(raw.pop("local", {}) or {})),
            "analysis_bundle": AnalysisBundleSettings(**(raw.pop("analysis_bundle", {}) or {})),
            "live": _live_settings(raw.pop("live", {}) or {}),
        }
        # Three states, not two. The environment wins over the settings file (unchanged
        # precedence); a profile written into the file is still a deliberate choice; and only
        # when NEITHER names one is the ``local`` binding inherited rather than consented to.
        # The old ``os.environ.get(_PROFILE_ENV, raw.pop("profile", "local"))`` collapsed the
        # third state into the first, so a missing env var served the no-auth persona stack.
        choice = resolve_profile()
        file_profile = str(raw.pop("profile", "") or "").strip()
        if choice.explicit:
            profile, explicit = choice.profile, True
        elif file_profile:
            profile, explicit = _validate_profile(file_profile), True
        else:
            profile, explicit = choice.profile, False
        known = {f for f in Settings.__dataclass_fields__ if f not in nested}
        flat: dict[str, Any] = {k: v for k, v in raw.items() if k in known}
        flat.pop("profile_explicit", None)
        return Settings(profile=profile, profile_explicit=explicit, **flat, **nested)


def instantiate(dotted: str, settings: Settings) -> Any:
    """Import ``module.path:ClassName`` and construct it with ``settings``."""
    module_path, _, class_name = dotted.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(settings)


class Container:
    """Lazily-built registry of port -> adapter instances.

    Adapters are imported only on first access so that, e.g., a unit test using the
    on-prem profile never needs the Google Cloud SDKs installed.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _bind(self, port_name: str) -> Any:
        binding = self.settings.adapters.get(port_name, {})
        dotted = binding.get(self.settings.profile)
        if not dotted:
            raise KeyError(
                f"No adapter configured for port '{port_name}' "
                f"under profile '{self.settings.profile}'."
            )
        return instantiate(dotted, self.settings)

    # One cached_property per port keeps wiring declarative and type-greppable.
    @cached_property
    def analysis_bundle(self) -> Any:
        return self._bind("analysis_bundle")

    @cached_property
    def extraction(self) -> Any:
        return self._bind("extraction")

    @cached_property
    def knowledge_base(self) -> Any:
        return self._bind("knowledge_base")

    @cached_property
    def peer_data(self) -> Any:
        return self._bind("peer_data")

    @cached_property
    def llm(self) -> Any:
        return self._bind("llm")

    @cached_property
    def guardrail(self) -> Any:
        return self._bind("guardrail")

    @cached_property
    def redaction(self) -> Any:
        return self._bind("redaction")

    @cached_property
    def audit(self) -> Any:
        return self._bind("audit")

    @cached_property
    def tracer(self) -> Any:
        return self._bind("tracer")

    @cached_property
    def evaluation(self) -> Any:
        return self._bind("evaluation")

    @cached_property
    def agent_registry(self) -> Any:
        return self._bind("agent_registry")

    @cached_property
    def tool_catalog(self) -> Any:
        return self._bind("tool_catalog")

    @cached_property
    def identity(self) -> Any:
        return self._bind("identity")

    @cached_property
    def review_router(self) -> Any:
        return self._bind("review_router")


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.load())


def identity_adapter_class(settings: Settings) -> type:
    """The identity adapter CLASS the active binding names, resolved WITHOUT constructing it.

    Reads the same ``adapters:`` table :meth:`Container._bind` binds from, so a deployment is
    answered about the adapter it ACTUALLY runs rather than the one the profile name suggests.
    A deployment that rebound identity in ``config/settings.yaml`` (the documented
    on-premises path: swap the placeholder for the client's own IdP adapter) is answered
    about that.

    Constructing is deliberately avoided: the seeded-persona adapter REFUSES to construct
    under an inherited profile, so a posture computed from an instance would be unobtainable
    in one of the exact cases it has to describe.
    """
    binding = settings.adapters.get("identity", {})
    dotted = binding.get(settings.profile)
    if not dotted:
        raise KeyError(f"No identity adapter configured under profile '{settings.profile}'.")
    module_path, _, class_name = dotted.partition(":")
    resolved = getattr(importlib.import_module(module_path), class_name)
    if not isinstance(resolved, type):
        raise TypeError(f"identity binding {dotted!r} does not name a class")
    return resolved


def end_user_auth_kind(settings: Settings | None = None) -> str:
    """What the BOUND identity adapter declares it does for end-user authentication.

    This is the one question "are this service's end-user routes authenticated?" reduces to.
    See ``ports/identity.py``: neither the profile string nor the presence of a
    service-to-service secret can answer it.

    Any failure to establish the answer resolves to ``CLIENT_ASSERTED``. A guard that switches
    OFF because a lookup raised is a guard that fails open, and nothing is lost by failing
    closed here: the same failure surfaces loudly at the first request, when the container
    resolves the identical binding for real.
    """
    from .ports.identity import CLIENT_ASSERTED, declared_end_user_auth

    try:
        return declared_end_user_auth(identity_adapter_class(settings or Settings.load()))
    except Exception:
        return CLIENT_ASSERTED
