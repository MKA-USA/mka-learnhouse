"""MKA fork: "who do I contact" counterparts for a viewer (contract s2.3).

``CounterpartsProvider`` is the seam: v1 is :class:`MailboxProvider`, which derives role mailboxes from the SAME rules file the
identity parser uses (no hard-coded department / region / Majlis lists). A later provider can return real names (``name``).
Mailboxes are never verified to exist: they are the org's mailbox *conventions*, the inverse of ``parse_identity``.

Rows, in order: national (the viewer's department head), regional (the department's regional nazim, then the regional Qaid, of the viewer's region), local (the
department's Majlis nazim at the viewer's Majlis). A row for the viewer's own address is dropped.
"""

from __future__ import annotations

from typing import Optional, Protocol

from src.services.mka.identity_parser import IdentityRules, slugify_majlis

# Local executive roles: they have no department head to contact, only their regional Qaid.
LOCAL_EXECUTIVE_ROLES = frozenset({"qaid", "naib_qaid", "motamid"})
RECOGNIZED = ("matched", "partial")


class CounterpartsProvider(Protocol):
    def for_viewer(self, attrs: dict, rules: IdentityRules) -> list[dict]: ...


def _row(level: str, role_title: Optional[str], email: str, department: Optional[str]) -> dict:
    return {"level": level, "role_title": role_title or "", "email": email, "name": None, "department": department}


class MailboxProvider:
    """Counterparts from mailbox conventions in the identity rules."""

    # -- rules lookups ------------------------------------------------------------------------------------
    @staticmethod
    def _national_mailbox(rules: IdentityRules, department: str) -> Optional[tuple[str, str, dict]]:
        fallback = None
        for domain, dom in rules.domains.items():
            for key, entry in dom.get("national_exact", {}).items():
                if entry.get("department") != department or entry.get("status", "matched") != "matched":
                    continue
                if entry.get("role") == "mohtamim":
                    return domain, key, entry
                fallback = fallback or (domain, key, entry)
        return fallback

    @staticmethod
    def _regional_qaid_prefix(rules: IdentityRules) -> Optional[tuple[str, str, str]]:
        for domain, dom in rules.domains.items():
            for prefix, entry in dom.get("local_prefixes", {}).items():
                if entry.get("regional") == "regional_qaid":
                    return domain, prefix, "regional_qaid"
        return None

    @staticmethod
    def _local_mailbox(rules: IdentityRules, department: str) -> Optional[tuple[str, str, dict]]:
        fallback = None
        for domain, dom in rules.domains.items():
            for prefix, entry in dom.get("local_prefixes", {}).items():
                if entry.get("department") != department:
                    continue
                if str(entry.get("role", "")).startswith("nazim"):
                    return domain, prefix, entry
                fallback = fallback or (domain, prefix, entry)
        return fallback

    @staticmethod
    def _regional_dept_mailbox(rules: IdentityRules, department: str) -> Optional[tuple[str, str, dict]]:
        """``{prefix}.{region slug}@domain`` convention of a department: a local prefix that declares a ``regional`` role.
        Domains without one (atfalusa.org) have no regional pattern, so such departments get no row."""
        for domain, dom in rules.domains.items():
            for prefix, entry in dom.get("local_prefixes", {}).items():
                if entry.get("department") == department and entry.get("regional"):
                    return domain, prefix, entry
        return None

    @staticmethod
    def _region_slug(rules: IdentityRules, region: str) -> Optional[str]:
        for slug, name in rules.regions.items():
            if name == region:
                return slug
        return None

    @staticmethod
    def _majlis_slug(rules: IdentityRules, domain: str, majlis: str) -> str:
        """The slug under which ``domain`` addresses a Majlis: a domain/global alias if one points at it, else the generated one."""
        for aliases in (rules.domains.get(domain, {}).get("slug_aliases", {}), rules.slug_aliases):
            for slug, name in aliases.items():
                if name == majlis:
                    return slug
        return slugify_majlis(majlis)

    # -- rows ---------------------------------------------------------------------------------------------
    @staticmethod
    def _regional_office_mailbox(rules: IdentityRules, region: str) -> Optional[tuple[str, str]]:
        """A national mailbox the rules mark as ALSO being the office of ``region`` (``region`` key on a ``national_exact`` entry):
        Muqami is its own region and chapter, and its Qaid mailbox is the national ``muqami@`` (there is no ``qaid.muqami@``)."""
        for domain, dom in rules.domains.items():
            for key, entry in dom.get("national_exact", {}).items():
                if entry.get("region") == region and entry.get("status", "matched") == "matched":
                    return domain, key
        return None

    def _regional_row(self, attrs: dict, rules: IdentityRules) -> Optional[dict]:
        region = attrs.get("region")
        if not isinstance(region, str) or not region:
            return None
        found = self._regional_qaid_prefix(rules)
        slug = self._region_slug(rules, region)
        if found and slug:
            domain, prefix, role = found
            return _row("regional", rules.title(role, "regional", None), f"{prefix}.{slug}@{domain}", None)
        office = self._regional_office_mailbox(rules, region)
        if office:
            return _row("regional", rules.title("regional_qaid", "regional", None), f"{office[1]}@{office[0]}", None)
        return None

    def for_viewer(self, attrs: dict, rules: IdentityRules) -> list[dict]:
        if attrs.get("status") not in RECOGNIZED:
            return []
        role, department, level = attrs.get("role"), attrs.get("department"), attrs.get("level")
        if role in LOCAL_EXECUTIVE_ROLES and level != "national":
            row = self._regional_row(attrs, rules)
            return [row] if row else []
        if not department:
            return []

        rows: list[dict] = []
        national = self._national_mailbox(rules, department)
        if national:
            domain, key, entry = national
            rows.append(_row("national", rules.title(entry.get("role"), "national", department), f"{key}@{domain}", department))
        region_slug = self._region_slug(rules, attrs["region"]) if isinstance(attrs.get("region"), str) else None
        regional_dept = self._regional_dept_mailbox(rules, department)
        if regional_dept and region_slug:
            domain, prefix, entry = regional_dept
            if not (level == "regional" and role == entry["regional"]):  # that mailbox is the viewer's own role
                rows.append(_row("regional", rules.title(entry["regional"], "regional", department), f"{prefix}.{region_slug}@{domain}", department))
        regional = self._regional_row(attrs, rules)
        if regional:
            rows.append(regional)
        majlis = attrs.get("majlis")
        local = self._local_mailbox(rules, department)
        if local and isinstance(majlis, str) and majlis:
            domain, prefix, entry = local
            same_role = level == "local" and role == entry.get("role")  # that mailbox is the viewer's own role
            if not same_role:
                rows.append(_row(
                    "local", rules.title(entry.get("role"), "local", department),
                    f"{prefix}.{self._majlis_slug(rules, domain, majlis)}@{domain}", department,
                ))
        return rows


DEFAULT_PROVIDER: CounterpartsProvider = MailboxProvider()


def _address_key(email: Optional[str]) -> str:
    """Lower-cased address without plus-tag (the parser treats ``a+x@d`` as ``a@d``)."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    local, domain = e.rsplit("@", 1)
    return f"{local.split('+', 1)[0]}@{domain}"


def counterparts_for(
    attrs: dict, rules: IdentityRules, own_email: Optional[str] = None, provider: Optional[CounterpartsProvider] = None
) -> dict:
    """The ``Counterparts`` response body for a viewer's EFFECTIVE (fail-closed) attributes."""
    provider = provider or DEFAULT_PROVIDER
    if attrs.get("status") not in RECOGNIZED:
        return {"counterparts": [], "reason": "unrecognized"}
    if not attrs.get("department") and attrs.get("role") not in LOCAL_EXECUTIVE_ROLES:
        return {"counterparts": [], "reason": "no_department"}
    own = _address_key(own_email)
    rows: list[dict] = []
    seen: set[str] = set()
    for r in provider.for_viewer(attrs, rules):
        key = _address_key(r["email"])
        if (own and key == own) or key in seen:  # own address, or a mailbox already listed (muqami@ is national AND chapter Qaid)
            continue
        seen.add(key)
        rows.append(r)
    return {"counterparts": rows, "reason": None}

