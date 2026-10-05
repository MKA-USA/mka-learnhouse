"""MKA fork: pure, table-driven email -> identity-attributes parser (spec A4).

No I/O, never raises. All organisational knowledge (departments, mailbox
prefixes, regions, aliases, titles) lives in the versioned rules file
``identity_rules/<version>.json``; the Majlis -> Region map is the single
source ``MAJLIS_TO_REGION`` in ``services/users/mka_profile.py``.

Precedence of the algorithm (first match wins):
  1. normalise + validate the address            -> else ``unrecognized``
  2. domain not an officeholder domain           -> ``not_applicable``
  3. explicit personal-name mailbox              -> ``matched``
  4. no dot in local part: national role mailbox -> ``matched`` / rule status
  5. ``{prefix}.{slug}``: resolve the slug against Majlis / Region lists;
     a slug that is truly both a Region and a Majlis under a regional-capable
     prefix is ``ambiguous`` (never guessed)
  6. anything else                               -> ``unrecognized``
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

RULES_DIR = Path(__file__).resolve().parent / "identity_rules"
DEFAULT_RULES_VERSION = "2026.1"

STATUSES = ("matched", "partial", "ambiguous", "unrecognized", "not_applicable")
LEVELS = ("national", "regional", "local")

FLAG_NEEDS_REVIEW = "needs_review"
FLAG_AMBIGUOUS = "ambiguous_slug"


@dataclass
class MkaAttributes:
    status: str
    is_officeholder: Optional[bool] = None
    level: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    role_title: Optional[str] = None
    majlis: Optional[str] = None
    region: Optional[str] = None
    source: str = "parser"
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "is_officeholder": self.is_officeholder,
            "level": self.level,
            "department": self.department,
            "role": self.role,
            "role_title": self.role_title,
            "majlis": self.majlis,
            "region": self.region,
            "source": self.source,
            "flags": list(self.flags),
        }


def slugify_majlis(name: str) -> str:
    """Lowercase, spaces removed, hyphens kept ("Syracuse-Binghamton" stays hyphenated)."""
    return name.lower().replace(" ", "")


class IdentityRules:
    """Rules file + Majlis map, indexed for lookups."""

    def __init__(self, raw: dict, majlis_to_region: dict[str, str]):
        self.raw = raw
        self.version: str = raw["version"]
        self.majlis_to_region = dict(majlis_to_region)
        self.majlis_by_slug: dict[str, str] = {
            slugify_majlis(m): m for m in self.majlis_to_region
        }
        self.regions: dict[str, str] = dict(raw.get("regions", {}))
        self.slug_aliases: dict[str, str] = dict(raw.get("slug_aliases", {}))
        self.unconfirmed_slugs: set[str] = set(raw.get("unconfirmed_slugs", []))
        self.role_titles: dict[str, str] = dict(raw.get("role_titles", {}))
        self.department_names: dict[str, str] = {
            d["key"]: d["name"] for d in raw.get("departments", [])
        }
        self.domains: dict[str, dict] = dict(raw.get("domains", {}))

    @classmethod
    def from_dict(cls, raw: dict, majlis_to_region: dict[str, str]) -> "IdentityRules":
        rules = cls(raw, majlis_to_region)
        dupes = rules.collisions()
        if dupes:
            logger.warning(
                "MKA identity rules %s: slugs are both a Region and a Majlis: %s",
                rules.version, ", ".join(dupes),
            )
        return rules

    # -- introspection ---------------------------------------------------------
    def collisions(self) -> list[str]:
        """Slugs that name both a Region and a Majlis (ambiguous under `qaid.`)."""
        return sorted(set(self.regions) & set(self.majlis_by_slug))

    # -- helpers -----------------------------------------------------------------
    def resolve_majlis(self, domain: str, slug: str) -> Optional[str]:
        """Canonical Majlis name for a slug (domain alias, global alias, generated)."""
        dom_aliases = self.domains.get(domain, {}).get("slug_aliases", {})
        return dom_aliases.get(slug) or self.slug_aliases.get(slug) or self.majlis_by_slug.get(slug)

    def title(self, role: Optional[str], level: Optional[str], department: Optional[str]) -> Optional[str]:
        if not role:
            return None
        tpl = self.role_titles.get(f"{role}:{level}") or self.role_titles.get(role)
        if tpl is None:
            return None
        dept_name = self.department_names.get(department or "", "")
        return tpl.replace("{department}", dept_name).strip()


def _rules_path(version: str) -> Path:
    return RULES_DIR / f"{version}.json"


@lru_cache(maxsize=4)
def load_rules(version: str = DEFAULT_RULES_VERSION) -> IdentityRules:
    from src.services.users.mka_profile import MAJLIS_TO_REGION  # canonical map

    with open(_rules_path(version), "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return IdentityRules.from_dict(raw, MAJLIS_TO_REGION)


# ---------------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------------

def _unrecognized() -> MkaAttributes:
    return MkaAttributes(status="unrecognized", is_officeholder=None)


def parse_identity(email: Any, rules: IdentityRules) -> MkaAttributes:
    """Derive attributes from a (Google-verified) email. Never raises."""
    try:
        return _parse(email, rules)
    except Exception:  # noqa: BLE001 - contract: any failure is "unrecognized"
        logger.exception("MKA identity parse failed")
        return _unrecognized()


def _make(
    rules: IdentityRules,
    entry: dict,
    *,
    status: str,
    level: Optional[str],
    role: Optional[str],
    majlis: Optional[str] = None,
    region: Optional[str] = None,
    department_from_entry: bool = True,
    extra_flags: tuple[str, ...] = (),
) -> MkaAttributes:
    dept = entry.get("department") if department_from_entry else None
    flags = list(entry.get("flags", [])) + [f for f in extra_flags if f not in entry.get("flags", [])]
    return MkaAttributes(
        status=status,
        is_officeholder=True,
        level=level,
        department=dept,
        role=role,
        role_title=rules.title(role, level, dept) if status != "ambiguous" else None,
        majlis=majlis,
        region=region,
        flags=flags,
    )


def _parse(email: Any, rules: IdentityRules) -> MkaAttributes:
    if not isinstance(email, str):
        return _unrecognized()
    e = email.strip().lower()
    if not e or any(ch.isspace() for ch in e) or e.count("@") != 1:
        return _unrecognized()
    local, domain = e.split("@")
    local = local.split("+", 1)[0]  # plus-addressing: tabligh.albany+x@ == tabligh.albany@
    if not local or not domain:
        return _unrecognized()

    dom = rules.domains.get(domain)
    if dom is None:
        return MkaAttributes(status="not_applicable", is_officeholder=False)

    personal = dom.get("personal_mailboxes", {}).get(local)
    if personal is not None:
        return _make(rules, personal, status="matched", level=personal.get("level", "national"),
                     role=personal.get("role"))

    if "." not in local:
        nat = dom.get("national_exact", {}).get(local)
        if nat is None:
            return _unrecognized()
        status = nat.get("status", "matched")
        if status != "matched":
            # Known mailbox, unresolved meaning: keep what the rule says, nothing more.
            return _make(rules, nat, status=status, level=nat.get("level"), role=nat.get("role"))
        return _make(rules, nat, status="matched", level="national", role=nat.get("role"))

    parts = local.split(".")
    if len(parts) != 2:
        return _unrecognized()
    prefix, slug = parts
    entry = dom.get("local_prefixes", {}).get(prefix)
    if entry is None or not slug:
        return _unrecognized()

    # An unconfirmed slug is known-but-unresolved: never guess a Majlis or level.
    if slug in rules.unconfirmed_slugs:
        return _make(rules, entry, status="partial", level=None, role=entry.get("role"),
                     extra_flags=(FLAG_NEEDS_REVIEW, "unconfirmed_slug"))

    majlis = rules.resolve_majlis(domain, slug)
    region_name = rules.regions.get(slug)
    regional_role = entry.get("regional")

    if regional_role and region_name and majlis:
        # `qaid.{slug}` where the slug is both a Region and a Majlis: refuse to guess.
        return MkaAttributes(
            status="ambiguous", is_officeholder=True, level=None, department=None, role=None,
            flags=[FLAG_NEEDS_REVIEW, FLAG_AMBIGUOUS],
        )
    if regional_role and region_name and not majlis:
        return _make(rules, entry, status="matched", level="regional", role=regional_role,
                     region=region_name)
    if majlis:
        return _make(rules, entry, status="matched", level="local", role=entry.get("role"),
                     majlis=majlis, region=rules.majlis_to_region[majlis])
    # Role known, slug unknown (new Majlis, or a Region used where no regional role exists).
    return _make(rules, entry, status="partial", level=None, role=entry.get("role"))
