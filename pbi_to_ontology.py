"""
Power BI semantic model  ->  ontology draft + gap report

Reads an exported model definition (TMSL / .bim JSON) and produces two files:

  ontology.yaml    what the model already encodes, as a draft ontology
  gap_report.md    what an ontology needs that a tabular model cannot hold

The second file is the point. The first is mostly mechanical translation.

Usage:
    python pbi_to_ontology.py model.bim
    python pbi_to_ontology.py model.bim --out-dir output --name "O2B Finance"

No connection, no credentials, no .NET. It parses a file.

------------------------------------------------------------------------------
How to get the .bim file, pick whichever is easiest for you
------------------------------------------------------------------------------

1. Tabular Editor 2 (free, the usual tool in the Power BI world)
   Open it, File > Open > From DB, pick the running Desktop instance,
   then File > Save As > model.bim

2. Power BI Project format
   In Desktop, File > Save As and choose .pbip. That writes a folder with the
   model definition in it. If your version writes TMDL (.tmdl files) rather
   than a .bim, use route 1 or 3 instead, this script reads TMSL JSON.

3. The Power BI modeling bridge you already have
   Its model_operations tool has an ExportTMSL operation. Export to a file and
   point this script at it.

Nothing here is specific to one model. Run it on any .bim.
"""

import argparse
import json
import os
import re
from collections import defaultdict

# Tabular defaults. TMSL leaves these out when they hold the default value,
# which is a common source of wrong conclusions if you forget it.
DEFAULT_FROM_CARD = "many"
DEFAULT_TO_CARD = "one"
DEFAULT_CROSSFILTER = "oneDirection"

# Column names that often carry coded values. The model file holds no data, so
# this is a prompt to go and look, not a finding.
CODE_HINTS = re.compile(
    r"(^|_)(code|cd|status|sts|type|flag|ind|indicator|category|class|level|"
    r"stage|reason|source|channel|segment|tier|grade)s?$"
)


# Power BI generates a hidden date table for every date column when the
# "Auto date/time" option is on, plus one template. They are machinery, not
# business entities, so they are excluded from every count. Leaving them in
# inflates the table count and reports their relationships as ambiguities.
AUTO_TABLE = re.compile(r"^(LocalDateTable_|DateTableTemplate_)")


def strip_auto_tables(model):
    """Remove auto-generated date tables and any relationship touching them.
    Returns how many were removed, so the report can mention it."""
    auto_names = {t["name"] for t in model["tables"] if AUTO_TABLE.match(t["name"])}
    if not auto_names:
        return 0
    model["tables"] = [t for t in model["tables"] if t["name"] not in auto_names]
    model["relationships"] = [
        r for r in model.get("relationships", [])
        if r.get("fromTable") not in auto_names and r.get("toTable") not in auto_names
    ]
    return len(auto_names)


def looks_coded(name):
    """StatusCd, segment_code and SEGMENTCODE should all match, so split
    camelCase into words before testing the suffix."""
    n = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    n = re.sub(r"[^0-9a-zA-Z_]", "_", n).lower()
    return bool(CODE_HINTS.search(n))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_model(path):
    with open(path, encoding="utf-8-sig") as f:
        doc = json.load(f)
    # A .bim wraps the model; some exports hand you the model directly.
    model = doc.get("model", doc)
    if "tables" not in model:
        raise SystemExit(
            f"{path} does not look like a TMSL model file. Expected a 'model' "
            f"object with a 'tables' array. Top-level keys found: {list(doc)[:8]}"
        )
    return doc.get("name") or model.get("name") or os.path.basename(path), model


def anonymize_model(model):
    """
    Strip every identifying name out of the model while keeping its shape.

    Counts, cardinalities, ambiguities, rule shapes and coverage percentages
    all survive. Table names, column names, measure names, descriptions and
    DAX literals do not. The result is a gap report you can show anyone,
    with no redaction by hand.

    Runs before any analysis, so the rest of the script never sees a real name.
    """
    table_map = {}          # table -> alias
    col_map = {}            # (table, column) -> alias, because two tables can
                            # both have an EmployeeKey and they are not the same
    token_map = {}          # bare token -> alias, used only for scrubbing DAX

    for i, t in enumerate(model["tables"], 1):
        ta = f"Table_{i}"
        table_map[t["name"]] = ta
        token_map.setdefault(t["name"], ta)
        for j, c in enumerate(t.get("columns", []), 1):
            ca = f"{ta}_Col_{j}"
            col_map[(t["name"], c["name"])] = ca
            token_map.setdefault(c["name"], ca)
            # Decide this before renaming, or the heuristic has nothing to read.
            c["_coded"] = looks_coded(c["name"])
        for k, m in enumerate(t.get("measures", []), 1):
            token_map.setdefault(m["name"], f"{ta}_Measure_{k}")

    # Relationships first, while the original names are still in place.
    for r in model.get("relationships", []):
        ft, tt = r.get("fromTable"), r.get("toTable")
        r["fromColumn"] = col_map.get((ft, r.get("fromColumn")), "Col_unknown")
        r["toColumn"] = col_map.get((tt, r.get("toColumn")), "Col_unknown")
        r["fromTable"] = table_map.get(ft, ft)
        r["toTable"] = table_map.get(tt, tt)

    # Longest first, so "Sales Order" is replaced before "Sales".
    ordered = sorted(token_map.items(), key=lambda kv: -len(kv[0]))

    def scrub(text):
        if not text:
            return text
        for original, alias in ordered:
            # Word boundaries stop "Date" matching inside "DateKey", and the
            # lookahead stops a table called Date from eating the DATE()
            # function. Both happen in real models.
            text = re.sub(
                r"\b" + re.escape(original) + r"\b(?!\s*\()",
                alias, text, flags=re.IGNORECASE,
            )
        # Anything still quoted is a literal, which may be a status code or a
        # customer name. Keep the shape, drop the content.
        return re.sub(r'"[^"]*"', '"<value>"', text)

    for t in model["tables"]:
        for m in t.get("measures", []):
            m["expression"] = scrub(expr(m))

    # Now rename the objects themselves.
    for t in model["tables"]:
        original_table = t["name"]
        for c in t.get("columns", []):
            c["name"] = col_map[(original_table, c["name"])]
            if c.get("description"):
                c["description"] = "redacted"
        for k, m in enumerate(t.get("measures", []), 1):
            m["name"] = f"{table_map[original_table]}_Measure_{k}"
            if m.get("description"):
                m["description"] = "redacted"
        if t.get("description"):
            t["description"] = "redacted"
        t["name"] = table_map[original_table]

    return model


def desc(obj):
    """TMSL descriptions are sometimes a string and sometimes a list of lines."""
    d = obj.get("description")
    if isinstance(d, list):
        d = " ".join(d)
    return (d or "").strip()


def expr(obj, key="expression"):
    e = obj.get(key)
    if isinstance(e, list):
        e = "\n".join(e)
    return (e or "").strip()


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def relationships_of(model):
    """Normalise relationships and fill in the defaults TMSL omits."""
    out = []
    for r in model.get("relationships", []):
        out.append(
            {
                "name": r.get("name", ""),
                "from_table": r.get("fromTable", ""),
                "from_column": r.get("fromColumn", ""),
                "to_table": r.get("toTable", ""),
                "to_column": r.get("toColumn", ""),
                "from_card": r.get("fromCardinality", DEFAULT_FROM_CARD),
                "to_card": r.get("toCardinality", DEFAULT_TO_CARD),
                "active": r.get("isActive", True),
                "crossfilter": r.get("crossFilteringBehavior", DEFAULT_CROSSFILTER),
            }
        )
    return out


def classify_tables(model, rels):
    """
    Fact, dimension, date or calculated.

    The heuristic: a table on the 'many' side of relationships and carrying
    measures behaves like a fact. A table on the 'one' side behaves like a
    dimension. It is a heuristic, not a truth, and the gap report says so.
    """
    many_side = {r["from_table"] for r in rels if r["from_card"] == "many"}
    one_side = {r["to_table"] for r in rels if r["to_card"] == "one"}

    kinds = {}
    for t in model["tables"]:
        name = t["name"]
        has_measures = bool(t.get("measures"))
        calculated = any(
            (p.get("source") or {}).get("type") == "calculated"
            for p in t.get("partitions", [])
        )
        if t.get("dataCategory") == "Time":
            kind = "date"
        elif name in many_side and name not in one_side:
            kind = "fact"
        elif name in one_side and name not in many_side:
            kind = "dimension"
        elif has_measures and name in many_side:
            kind = "fact"
        elif name in one_side:
            kind = "dimension"
        elif has_measures and not [c for c in t.get("columns", []) if not c.get("isHidden")]:
            # A table that holds only measures is an organising device, not a
            # business entity. Common pattern, and it should not become a class.
            kind = "measure_container"
        else:
            kind = "standalone"
        kinds[name] = {"kind": kind, "calculated": calculated}
    return kinds


def identifier_of(table, rels):
    """Declared key, else the column other tables join to, else nothing."""
    for c in table.get("columns", []):
        if c.get("isKey"):
            return c["name"], "declared isKey"
    joined = {r["to_column"] for r in rels if r["to_table"] == table["name"]}
    if len(joined) == 1:
        return next(iter(joined)), "inferred from relationships"
    if joined:
        return sorted(joined)[0], f"ambiguous, {len(joined)} columns are joined to"
    return None, "none found"


# ---------------------------------------------------------------------------
# DAX mining. This is where the undeclared business rules are hiding.
# ---------------------------------------------------------------------------

STRING_LITERAL = re.compile(r'"([^"]{1,60})"')
COMPARISON = re.compile(
    r"\[([^\]]+)\]\s*(=|<>|>=|<=|>|<)\s*(\"[^\"]*\"|-?\d+(?:\.\d+)?)"
)
USEREL = re.compile(r"USERELATIONSHIP\s*\(", re.IGNORECASE)
# CALCULATE ( ..., Table[Col] IN { "A", "B" } ). A set filter is the same kind
# of rule as an equality one and has to be caught too.
IN_SET = re.compile(r"\[([^\]]+)\]\s+IN\s*\{([^}]*)\}", re.IGNORECASE)
HARDCODED_DATE = re.compile(r'DATE\s*\(\s*(\d{4})\s*,', re.IGNORECASE)


def mine_dax(measures):
    """
    Pull the implicit rules out of measure logic.

    A filter like Status = "C" inside a CALCULATE is a business rule. It is
    load-bearing, it is invisible to anyone reading the report, and it exists
    nowhere else in the model. Surfacing these is the highest-value thing this
    script does, because each one is a line that belongs in the ontology.
    """
    findings = []
    for m in measures:
        e = m["expression"]
        if not e:
            continue
        hits = []
        for col, op, val in COMPARISON.findall(e):
            hits.append(f"[{col}] {op} {val}")
        for col, members in IN_SET.findall(e):
            hits.append(f"[{col}] IN {{{members.strip()}}}")
        for y in HARDCODED_DATE.findall(e):
            hits.append(f"hardcoded year {y}")
        if USEREL.search(e):
            hits.append("USERELATIONSHIP, activates an inactive relationship")
        if hits:
            findings.append({"measure": m["name"], "table": m["table"], "rules": hits})
    return findings


def duplicate_logic(measures):
    """Measures with identical logic under different names. The classic
    'two revenue definitions' problem, visible before anyone argues about it."""
    buckets = defaultdict(list)
    for m in measures:
        if not m["expression"]:
            continue
        # DAX ignores whitespace, so two people formatting the same logic
        # differently must still collide. Strip it all, not just collapse it.
        key = re.sub(r"\s+", "", m["expression"]).lower()
        buckets[key].append(f"{m['table']}[{m['name']}]")
    return [names for names in buckets.values() if len(names) > 1]


# ---------------------------------------------------------------------------
# Derivation. Everything below is produced mechanically from evidence in the
# model. It is proposed, never certified: a human still has to agree to it.
# ---------------------------------------------------------------------------

AGGREGATION = re.compile(
    r"\b(SUM|SUMX|AVERAGE|AVERAGEX|MIN|MAX|COUNT|COUNTA|DISTINCTCOUNT)\s*\(\s*"
    r"'?([^'\[\)]+?)'?\s*\[([^\]]+)\]",
    re.IGNORECASE,
)
MEASURE_REF = re.compile(r"\[([^\]]+)\]")

ROLE_WORDS = [
    (("date", "calendar", "time", "month", "week", "day"), "on{}"),
    (("location", "site", "store", "branch", "office", "region", "country"), "at{}"),
    (("category", "type", "class", "segment", "group"), "in{}"),
    (("customer", "client", "account", "party", "vendor", "supplier"), "for{}"),
    (("employee", "staff", "teacher", "person", "user"), "by{}"),
]


def clean_entity(name):
    """Dim_Location -> Location, V_FINANCIAL_DATA_PER_LOCATION_V1 -> FinancialDataPerLocation"""
    n = re.sub(r"^(Dim|Fact|V|vw|tbl)[_]", "", name, flags=re.IGNORECASE)
    n = re.sub(r"[_]?V\d+$", "", n)
    parts = [w for w in re.split(r"[_\s]+", n) if w]
    return "".join(w.capitalize() if w.isupper() else w[:1].upper() + w[1:] for w in parts)


def strip_key_suffix(col):
    """ManagerKey -> Manager, customer_id -> Customer, ShipDate -> ShipDate"""
    c = re.sub(r"(_?(key|id|code|cd|num|no))$", "", col, flags=re.IGNORECASE)
    return clean_entity(c) or clean_entity(col)


def propose_relationship_name(rel):
    """A name for an unnamed join, from what it points at. Proposed, not certified."""
    if rel["from_table"] == rel["to_table"]:
        # Self-reference. The target name says nothing, the column says everything.
        return f"has{strip_key_suffix(rel['from_column'])}"
    target = clean_entity(rel["to_table"])
    low = target.lower()
    for words, pattern in ROLE_WORDS:
        if any(w in low for w in words):
            return pattern.format(target)
    return f"has{target}"


def propose_grain(table_name, rels, identifier, table):
    """
    A fact table's grain is partly written in its relationships: one row per
    each dimension it points at.

    Partly, not wholly. A column that behaves like a dimension but has no
    dimension table behind it is invisible here, and the real grain is then
    finer than the relationships suggest. So this returns a candidate plus any
    columns that might break it, never a statement of fact.
    """
    targets, seen = [], set()
    for r in rels:
        if r["from_table"] != table_name:
            continue
        t = clean_entity(r["to_table"])
        if t not in seen:
            seen.add(t)
            targets.append(t)

    # A column is already accounted for if this table joins out through it, if
    # another table joins in to it, or if it is this table's own identifier.
    # Without the last two, every dimension gets flagged for its own key.
    accounted = {r["from_column"] for r in rels if r["from_table"] == table_name}
    accounted |= {r["to_column"] for r in rels if r["to_table"] == table_name}
    if identifier:
        accounted.add(identifier)
    unmodelled = [
        c["name"]
        for c in table.get("columns", [])
        if looks_coded(c["name"]) and not c.get("isHidden") and c["name"] not in accounted
    ]

    if targets:
        candidate = "one row per " + " per ".join(targets)
    elif identifier:
        candidate = f"one row per {identifier}"
    else:
        return None, unmodelled
    return candidate, unmodelled


def value_sets(dax_rules):
    """
    Collect every literal each column is compared against, across all measures.
    The result is the set of values the model actually depends on, which is a
    real constraint: a value outside it is silently excluded from the number.
    """
    sets = defaultdict(set)
    users = defaultdict(set)
    for f in dax_rules:
        for rule in f["rules"]:
            m = re.match(r"\[([^\]]+)\]\s*=\s*\"([^\"]*)\"", rule)
            if m:
                sets[m.group(1)].add(m.group(2))
                users[m.group(1)].add(f["measure"])
                continue
            m = re.match(r"\[([^\]]+)\]\s+IN\s*\{(.*)\}", rule)
            if m:
                for v in re.findall(r'"([^"]*)"', m.group(2)):
                    sets[m.group(1)].add(v)
                users[m.group(1)].add(f["measure"])
    return {c: (sorted(v), sorted(users[c])) for c, v in sets.items() if v}


def aggregated_columns(expression):
    return {(t.strip(), c.strip()) for _, t, c in AGGREGATION.findall(expression or "")}


def inconsistent_filters(measures, dax_rules, vsets):
    """
    Find measures that aggregate the same source columns as their siblings but
    skip a filter the siblings all apply.

    This generalises the kind of defect a person only spots by reading every
    measure side by side: one measure in a family quietly missing the filter
    that defines the family.
    """
    rules_by_measure = {f["measure"]: f["rules"] for f in dax_rules}
    findings = []
    for filtered_col, (_, _users) in vsets.items():
        # Which source columns do the measures that DO filter on this touch?
        guarded_sources = set()
        for m in measures:
            if any(f"[{filtered_col}]" in r for r in rules_by_measure.get(m["name"], [])):
                guarded_sources |= aggregated_columns(m["expression"])
        if not guarded_sources:
            continue
        for m in measures:
            if any(f"[{filtered_col}]" in r for r in rules_by_measure.get(m["name"], [])):
                continue
            own = aggregated_columns(m["expression"])
            shared = own & guarded_sources
            if shared:
                findings.append(
                    {
                        "measure": m["name"],
                        "table": m["table"],
                        "missing_filter_on": filtered_col,
                        "shared_sources": sorted(f"{t}[{c}]" for t, c in shared),
                        "siblings": sorted(_users)[:4],
                    }
                )
    return findings


def measure_dependencies(measures):
    """Which measures are built on which. Derivable, and it shows what a
    change to one definition would ripple into."""
    names = {m["name"] for m in measures}
    deps = {}
    for m in measures:
        refs = {r for r in MEASURE_REF.findall(m["expression"] or "") if r in names and r != m["name"]}
        if refs:
            deps[m["name"]] = sorted(refs)
    return deps


def describe_filters(rules):
    """Turn extracted DAX rules into a sentence. Mechanical, not interpretive."""
    out = []
    for r in rules:
        m = re.match(r"\[([^\]]+)\]\s*=\s*(.+)", r)
        if m and "IN" not in r:
            out.append(f"counts only rows where {m.group(1)} is {m.group(2)}")
            continue
        m = re.match(r"\[([^\]]+)\]\s+IN\s*\{(.*)\}", r)
        if m:
            out.append(f"counts only rows where {m.group(1)} is one of {m.group(2)}")
            continue
        out.append(r)
    return "; ".join(out)


# ---------------------------------------------------------------------------
# Ambiguity
# ---------------------------------------------------------------------------

def ambiguities(rels):
    inactive = [r for r in rels if not r["active"]]
    bidirectional = [r for r in rels if r["crossfilter"] == "bothDirections"]
    many_to_many = [
        r for r in rels if r["from_card"] == "many" and r["to_card"] == "many"
    ]

    # Role playing: the same pair of tables joined more than once, e.g. a fact
    # joined to Date on both order date and ship date. Physically one table,
    # ontologically two different relationships.
    pairs = defaultdict(list)
    for r in rels:
        pairs[(r["from_table"], r["to_table"])].append(r)
    role_playing = {k: v for k, v in pairs.items() if len(v) > 1}

    return inactive, bidirectional, many_to_many, role_playing


# ---------------------------------------------------------------------------
# Readiness scorecard
# ---------------------------------------------------------------------------

def scorecard(stats):
    """
    Sixteen things an ontology needs. A tabular model can supply some of them
    structurally, supplies others only if somebody filled them in, and cannot
    supply the rest at all. Marking which is which is the whole report.
    """
    t, c, m = stats["tables"], stats["columns"], stats["measures"]
    td, cd, md = stats["table_desc"], stats["col_desc"], stats["measure_desc"]
    ids = stats["with_identifier"]
    amb = stats["ambiguity_count"]

    def pct(a, b):
        return 0 if not b else round(a / b * 100)

    rows = [
        ("Classes identified", "present", f"{t} tables classified"),
        ("Class identifiers", "present" if ids == t else "partial",
         f"{ids} of {t} have one"),
        ("Properties typed", "present", f"{c} columns with data types"),
        ("Class descriptions", "present" if td == t else ("partial" if td else "absent"),
         f"{td} of {t} filled, {pct(td, t)}%"),
        ("Property descriptions", "present" if cd == c else ("partial" if cd else "absent"),
         f"{cd} of {c} filled, {pct(cd, c)}%"),
        ("Class hierarchy, subsumption", "absent",
         "tabular models have no inheritance, nothing to extract"),
        ("Named relationships", "absent",
         "Power BI relationships are unnamed column joins"),
        ("Relationship direction", "present", f"{stats['rels']} relationships"),
        ("Relationship cardinality", "present", "declared on every relationship"),
        ("Unambiguous paths", "present" if amb == 0 else "partial",
         f"{amb} ambiguity flags, see below"),
        ("Explicit grain", "absent", "implied by the table, never stated"),
        ("Measures with a formula", "present" if m else "absent", f"{m} measures"),
        ("Measure definitions in business language",
         "present" if md == m else ("partial" if md else "absent"),
         f"{md} of {m} described, {pct(md, m)}%"),
        ("Coded value meanings", "absent",
         f"{stats['code_candidates']} columns look coded, the file holds no data"),
        ("Business rules and constraints", "absent",
         f"{stats['dax_rule_count']} found hiding inside DAX, none declared"),
        ("Cross-system identity", "absent", "one model is one system's view"),
    ]
    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def yaml_escape(s):
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    return s.replace("\n", " ").strip()


def write_ontology(path, model_name, tables, kinds, rels, measures, derived):
    L = []
    a = L.append
    a("# Ontology draft, extracted from a Power BI semantic model.")
    a("#")
    a("# Everything here was derived mechanically. Nothing in it has been")
    a("# certified by a human. The TODO markers are where the model could not")
    a("# supply an answer, and they are the work, not an oversight.")
    a("")
    a("meta:")
    a(f'  source_model: "{yaml_escape(model_name)}"')
    a("  status: draft, uncertified")
    a("")
    a("classes:")
    for t in tables:
        name = t["name"]
        k = kinds[name]
        if k["kind"] == "measure_container":
            # A table that holds only measures is an organising device, not a
            # business thing. It gets a note, not a class.
            continue
        ident, how = identifier_of(t, rels)
        a(f"\n  {name}:")
        d = desc(t)
        a(f'    definition: "{yaml_escape(d)}"' if d else "    definition: TODO")
        a(f"    table_kind: {k['kind']}" + ("  # calculated table" if k["calculated"] else ""))
        a(f"    identifier: {ident or 'TODO'}" + (f"  # {how}" if ident else ""))
        g, unmodelled = propose_grain(name, rels, ident, t)
        if g:
            a(f"    grain_candidate: {g}")
            a("    grain: TODO confirm or correct the candidate above")
            if unmodelled:
                verb = "looks" if len(unmodelled) == 1 else "look"
                noun = "a dimension" if len(unmodelled) == 1 else "dimensions"
                a(f"    # careful: {', '.join(unmodelled)} {verb} like {noun} but")
                a("    # has no relationship, so the real grain may be finer than the candidate."
                  if len(unmodelled) == 1 else
                  "    # have no relationship, so the real grain may be finer than the candidate.")
        else:
            a("    grain: TODO state one row per what")
        cols = [c for c in t.get("columns", []) if not c.get("isHidden")]
        if cols:
            a("    properties:")
            for c in cols[:40]:
                cd = desc(c)
                line = f"      - {c['name']}  # {c.get('dataType', '?')}"
                if cd:
                    line += f", {yaml_escape(cd)[:60]}"
                a(line)
            if len(cols) > 40:
                a(f"      # ... and {len(cols) - 40} more")
    a("")
    a("relationships:")
    a("  # Power BI has no named relationships, so the names below were proposed")
    a("  # from what each join points at. They are a starting point: replace any")
    a("  # that does not say what the link actually means.")
    counts = defaultdict(int)
    for r in rels:
        counts[propose_relationship_name(r)] += 1
    seen = defaultdict(int)
    for r in rels:
        base = propose_relationship_name(r)
        if counts[base] == 1:
            r["_name"] = base
        else:
            # Two joins point at the same thing. A number would hide that they
            # mean different things. What distinguishes them is either where
            # they start, or which column they go through.
            same_source = [
                o for o in rels
                if o is not r and propose_relationship_name(o) == base
                and o["from_table"] == r["from_table"]
            ]
            if same_source:
                # Role-playing: one table joined twice, e.g. order date and
                # ship date. The column name is the role.
                prefix = base.split(clean_entity(r["to_table"]))[0] or "via"
                name = prefix + strip_key_suffix(r["from_column"])
            else:
                src = clean_entity(r["from_table"])
                name = src[:1].lower() + src[1:] + base[:1].upper() + base[1:]
            seen[name] += 1
            r["_name"] = name if seen[name] == 1 else f"{name}_{seen[name]}"
    for r in rels:
        a(f"\n  {r['_name']}:  # proposed")
        a(f"    from: {r['from_table']}")
        a(f"    to: {r['to_table']}")
        a(f"    cardinality: {r['from_card']}_to_{r['to_card']}")
        a(f"    via: {r['from_table']}.{r['from_column']} = {r['to_table']}.{r['to_column']}")
        if not r["active"]:
            a("    active: false  # an alternate path somebody chose not to use")
        if r["crossfilter"] == "bothDirections":
            a("    crossfilter: bothDirections  # ambiguous, resolve explicitly")
    a("")
    a("measures:")
    for m in measures:
        a(f"\n  {m['name']}:")
        d = m["description"]
        a(f'    definition: "{yaml_escape(d)}"' if d else "    definition: TODO")
        a(f"    home_table: {m['table']}")
        a(f'    formula_dax: "{yaml_escape(m["expression"])[:300]}"')
        rules = derived["rules_by_measure"].get(m["name"])
        if rules:
            a(f'    filters: "{yaml_escape(describe_filters(rules))}"  # derived from the DAX')
        else:
            a("    filters: none found in the DAX")
        dep = derived["deps"].get(m["name"])
        if dep:
            a(f"    built_from: [{', '.join(dep)}]")
        a("    owner: TODO who signs off on this definition")
    a("")
    a("value_sets:")
    if derived["vsets"]:
        a("  # Every literal the model compares each column against. This is the set")
        a("  # of values the numbers actually depend on. Anything outside it is")
        a("  # silently excluded, which is why it belongs in the ontology.")
        for col, (vals, users) in sorted(derived["vsets"].items()):
            a(f"\n  {col}:")
            a("    values: [" + ", ".join(f'"{v}"' for v in vals) + "]")
            a(f"    relied_on_by: [{', '.join(users)}]")
            a("    closed: TODO can a new value appear in the source? who approves it?")
    else:
        a("  # None found.")
    a("")
    a("constraints:")
    a("  # Generated from evidence in the model. Each one is proposed: it states")
    a("  # what the model already assumes, not what anybody has agreed to.")
    n = 0
    for col, (vals, users) in sorted(derived["vsets"].items()):
        n += 1
        a(f"\n  - id: {re.sub(r'[^0-9a-zA-Z]+', '_', col).strip('_').lower()}_observed_values")
        a(f"    observed: {col} is only ever compared against {vals},")
        a(f"      by {len(users)} measures.")
        a("    # That is what the model does, not what must be true. One of these")
        a("    # holds, and only a person can say which:")
        a("    #   a) these are the only valid values, anything else is a data error")
        a("    #   b) other values exist and are deliberately excluded")
        a("    #   c) other values exist and are being dropped by accident")
        a(f"    check_first: run a distinct on the source {col}. Any value not in the")
        a("      list above is counted by no measure at all.")
        a("    rule: TODO write it once a) b) or c) is settled")
        a("    severity: error")
        a("    status: proposed")
    for f_ in derived["inconsistent"]:
        n += 1
        a(f"\n  - id: {re.sub(r'[^0-9a-zA-Z]+', '_', f_['measure']).strip('_').lower()}_filter_check")
        a(f"    rule: {f_['measure']} aggregates {', '.join(f_['shared_sources'])} but applies no")
        a(f"      filter on {f_['missing_filter_on']}, unlike {', '.join(f_['siblings'])}.")
        a("    because: a measure in a family that skips the family's filter usually")
        a("      returns a number that does not mean what its name says.")
        a("    severity: error")
        a("    status: proposed, needs a human to confirm whether it is deliberate")
    if n == 0:
        a("  - id: TODO")
    a("")
    a("# Still TODO, and not derivable by any tool:")
    a("#   every class definition, the hierarchy, who owns each measure,")
    a("#   whether the proposed constraints above are correct.")
    a("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def write_gap_report(path, model_name, stats, rows, amb, dax_rules, dupes,
                     code_candidates, undescribed_measures, derived):
    inactive, bidirectional, many_to_many, role_playing = amb
    L = []
    a = L.append
    a(f"# Ontology gap report: {model_name}")
    a("")
    a("What this semantic model already encodes, and what an ontology needs that")
    a("it structurally cannot hold.")
    a("")

    present = sum(1 for r in rows if r[1] == "present")
    partial = sum(1 for r in rows if r[1] == "partial")
    a(f"**{present} of 16 present, {partial} partial, {16 - present - partial} absent.**")
    a("")
    a("| What an ontology needs | Status | Evidence |")
    a("|---|---|---|")
    for name, status, evidence in rows:
        mark = {"present": "present", "partial": "partial", "absent": "absent"}[status]
        a(f"| {name} | {mark} | {evidence} |")
    a("")

    a("## Model at a glance")
    a("")
    a(f"- Tables: {stats['tables']}")
    a(f"- Columns: {stats['columns']}, of which {stats['hidden_columns']} hidden")
    a(f"- Relationships: {stats['rels']}")
    a(f"- Measures: {stats['measures']}")
    if stats.get("auto_removed"):
        a("")
        a(f"**{stats['auto_removed']} auto-generated date tables excluded from every count above.**")
        a("Power BI creates a hidden date table for each date column when the")
        a("\"Auto date/time\" option is on. They are machinery, not business entities.")
        a("Worth knowing separately: that option bloats the model and gets in the way")
        a("of proper time intelligence, so it is usually turned off in favour of a")
        a("real date dimension. That is a modelling note, not an ontology gap.")
    a("")

    a("## 1. Undeclared business rules, found inside DAX")
    a("")
    a("Each line below is a rule that decides which rows count. It is load-bearing,")
    a("it is invisible to anyone reading the report, and it is written down nowhere")
    a("except inside one measure. Every one of these belongs in the ontology.")
    a("")
    if dax_rules:
        a("| Measure | Rule found in its logic |")
        a("|---|---|")
        for f_ in dax_rules:
            for rule in f_["rules"]:
                a(f"| {f_['table']}[{f_['measure']}] | `{rule}` |")
    else:
        a("None found. Either the logic is genuinely simple, or the filters live")
        a("in the Power Query layer, which this file does not expose.")
    a("")

    a("## 2. Path ambiguity")
    a("")
    a("Every item here is a place where more than one answer is possible and")
    a("somebody already made a silent choice. An ontology has to make the choice")
    a("explicit, which is why these are Phase 3 work and not trivia.")
    a("")
    if inactive:
        a(f"**{len(inactive)} inactive relationship" + ("s" if len(inactive) != 1 else "") + ".** An alternate path exists and was turned off:")
        for r in inactive:
            a(f"- {r['from_table']}.{r['from_column']} to {r['to_table']}.{r['to_column']}")
        a("")
    if role_playing:
        a(f"**{len(role_playing)} role-playing dimension" + ("s" if len(role_playing) != 1 else "") + ".** The same two tables joined more than once.")
        a("Physically one table, ontologically two different relationships:")
        for (ft, tt), rs in role_playing.items():
            cols = ", ".join(f"{r['from_column']}" for r in rs)
            a(f"- {ft} to {tt}, via {cols}")
        a("")
    if bidirectional:
        a(f"**{len(bidirectional)} bidirectional filter" + ("s" if len(bidirectional) != 1 else "") + ".** Filter flows both ways, which")
        a("makes the meaning of a number depend on what else is on the page:")
        for r in bidirectional:
            a(f"- {r['from_table']} to {r['to_table']}")
        a("")
    if many_to_many:
        a(f"**{len(many_to_many)} many-to-many relationship" + ("s" if len(many_to_many) != 1 else "") + ".** Usually a sign that an")
        a("entity has not been resolved to a single identity:")
        for r in many_to_many:
            a(f"- {r['from_table']} to {r['to_table']}")
        a("")
    if not any([inactive, role_playing, bidirectional, many_to_many]):
        a("None. The model has a single unambiguous path between every pair of tables.")
        a("")

    a("## 3. Measures that skip their family's filter")
    a("")
    a("A measure that aggregates the same source columns as its siblings but")
    a("applies none of their filters usually returns a number that does not mean")
    a("what its name says. Each of these needs a human to confirm whether it is")
    a("deliberate.")
    a("")
    if derived["inconsistent"]:
        for f_ in derived["inconsistent"]:
            a(f"- **{f_['measure']}** aggregates {', '.join(f_['shared_sources'])} with no filter on "
              f"`{f_['missing_filter_on']}`, while {', '.join(f_['siblings'])} all apply one.")
    else:
        a("None found. Every measure in each family applies the same filters.")
    a("")

    a("## 4. Value sets the numbers depend on")
    a("")
    if derived["vsets"]:
        a("These are the literals the model compares against. A value outside the")
        a("list is silently excluded with no error, so each list needs an owner and")
        a("a rule about what happens when a new value appears.")
        a("")
        a("| Column | Values the model knows about | Measures relying on it |")
        a("|---|---|---|")
        for col, (vals, users) in sorted(derived["vsets"].items()):
            a(f"| `{col}` | {', '.join(vals)} | {len(users)} |")
    else:
        a("None found.")
    a("")

    a("## 5. Competing definitions")
    a("")
    if dupes:
        a("Measures with identical logic under different names. Somebody will")
        a("eventually ask which one is correct:")
        for group in dupes:
            a(f"- {', '.join(group)}")
    else:
        a("No two measures share identical logic.")
    a("")

    a("## 6. Missing definitions")
    a("")
    a(f"{stats['table_desc']} of {stats['tables']} tables and "
      f"{stats['measure_desc']} of {stats['measures']} measures carry a description.")
    a("")
    if undescribed_measures:
        a("Measures with no description, which means their meaning exists only in DAX:")
        for name in undescribed_measures[:25]:
            a(f"- {name}")
        if len(undescribed_measures) > 25:
            a(f"- ... and {len(undescribed_measures) - 25} more")
    a("")

    a("## 7. Columns that look coded")
    a("")
    a("This file contains no data, so these are candidates to go and check, not")
    a("findings. Each one that does hold codes needs its values defined in words.")
    a("")
    if code_candidates:
        for col in code_candidates[:30]:
            a(f"- {col}")
        if len(code_candidates) > 30:
            a(f"- ... and {len(code_candidates) - 30} more")
    else:
        a("No obvious candidates by name.")
    a("")

    a("## 8. What cannot be extracted at all")
    a("")
    a("Not a shortcoming of this script. A tabular model has no way to express these.")
    a("")
    a("- **Hierarchy.** No inheritance, so a rule true of several classes must be")
    a("  restated on each one instead of declared once on a parent.")
    a("- **Relationship meaning.** Direction and cardinality are there. What the")
    a("  link means is not.")
    a("- **Constraints.** No equivalent of a business rule. Row level security is")
    a("  access control, not semantics.")
    a("- **Grain, stated.** Implied by the table, never written down.")
    a("- **Cross-system identity.** One model is one system's view of the world.")
    a("")

    a("## Sizing")
    a("")
    todo = (
        (stats["tables"] - stats["table_desc"])
        + (stats["measures"] - stats["measure_desc"])
        + stats["rels"]
    )
    a(f"- Definitions to write: {stats['tables'] - stats['table_desc']} classes, "
      f"{stats['measures'] - stats['measure_desc']} measures")
    a(f"- Relationships to name and give meaning: {stats['rels']}")
    a(f"- Rules to declare properly: {stats['dax_rule_count']} already found in DAX, plus whatever is not in DAX")
    a(f"- Ambiguities to resolve: {stats['ambiguity_count']}")
    a(f"- Coded columns to check: {stats['code_candidates']}")
    a("")
    a(f"Roughly **{todo} items** need a human decision before this domain has a")
    a("certified semantic foundation. That number is the scope of the work, and")
    a("it came from a model that already exists rather than from a guess.")
    a("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model_file", help="path to a TMSL / .bim JSON export")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--name", default=None, help="override the model name in the report")
    ap.add_argument("--anonymize", action="store_true",
                    help="strip all names, descriptions and DAX literals, keeping "
                         "structure and counts. Use for anything you will show "
                         "outside the client.")
    args = ap.parse_args()

    model_name, model = load_model(args.model_file)
    model_name = args.name or model_name
    auto_removed = strip_auto_tables(model)
    if args.anonymize:
        model = anonymize_model(model)
        model_name = args.name or "Redacted model"

    tables = model["tables"]
    rels = relationships_of(model)
    kinds = classify_tables(model, rels)

    measures = []
    for t in tables:
        for m in t.get("measures", []):
            measures.append(
                {
                    "name": m["name"],
                    "table": t["name"],
                    "expression": expr(m),
                    "description": desc(m),
                }
            )

    all_columns = [(t["name"], c) for t in tables for c in t.get("columns", [])]
    code_candidates = [
        f"{tn}[{c['name']}]"
        for tn, c in all_columns
        if c.get("_coded", looks_coded(c["name"])) and not c.get("isHidden")
    ]

    dax_rules = mine_dax(measures)
    dupes = duplicate_logic(measures)
    amb = ambiguities(rels)
    inactive, bidirectional, many_to_many, role_playing = amb

    stats = {
        "tables": len(tables),
        "columns": len(all_columns),
        "hidden_columns": sum(1 for _, c in all_columns if c.get("isHidden")),
        "rels": len(rels),
        "measures": len(measures),
        "table_desc": sum(1 for t in tables if desc(t)),
        "col_desc": sum(1 for _, c in all_columns if desc(c)),
        "measure_desc": sum(1 for m in measures if m["description"]),
        "with_identifier": sum(1 for t in tables if identifier_of(t, rels)[0]),
        "code_candidates": len(code_candidates),
        "auto_removed": auto_removed,
        "dax_rule_count": sum(len(f["rules"]) for f in dax_rules),
        "ambiguity_count": (
            len(inactive) + len(bidirectional) + len(many_to_many) + len(role_playing)
        ),
    }

    vsets = value_sets(dax_rules)
    inconsistent = inconsistent_filters(measures, dax_rules, vsets)
    derived = {
        "vsets": vsets,
        "inconsistent": inconsistent,
        "deps": measure_dependencies(measures),
        "rules_by_measure": {f["measure"]: f["rules"] for f in dax_rules},
    }

    rows = scorecard(stats)
    undescribed = [f"{m['table']}[{m['name']}]" for m in measures if not m["description"]]

    os.makedirs(args.out_dir, exist_ok=True)
    onto_path = os.path.join(args.out_dir, "ontology.yaml")
    gap_path = os.path.join(args.out_dir, "gap_report.md")

    write_ontology(onto_path, model_name, tables, kinds, rels, measures, derived)
    write_gap_report(gap_path, model_name, stats, rows, amb, dax_rules, dupes,
                     code_candidates, undescribed, derived)

    present = sum(1 for r in rows if r[1] == "present")
    partial = sum(1 for r in rows if r[1] == "partial")
    print(f"Model: {model_name}")
    if auto_removed:
        print(f"  excluded {auto_removed} auto-generated date tables")
    print(f"  {stats['tables']} tables, {stats['columns']} columns, "
          f"{stats['rels']} relationships, {stats['measures']} measures")
    print(f"  readiness: {present} of 16 present, {partial} partial")
    print(f"  {stats['dax_rule_count']} undeclared rules found inside DAX")
    print(f"  {stats['ambiguity_count']} path ambiguities")
    print(f"\n  wrote {onto_path}\n  wrote {gap_path}")


if __name__ == "__main__":
    main()
