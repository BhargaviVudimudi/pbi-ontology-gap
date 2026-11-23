# pbi-ontology-gap

Reads a Power BI semantic model and reports how much of an ontology it already
contains, and what is still missing.

No AI, no network calls, no credentials. It parses an exported model file and
writes two documents.

---

## The problem

A Power BI semantic model already holds about half an ontology. It knows the
tables, the relationships, the cardinality and the measure formulas.

What it cannot hold is the meaning. There is no inheritance, so you cannot say a
Customer is a kind of Party. Relationships are unnamed column joins, so the
model knows an Order points at a Customer but not that it was *placed by* one.
There is no way to express a business rule at all.

So the rules end up inside the measures. A revenue measure quietly filters to
one status code, and that filter decides every number on the page. It is
load bearing, it is invisible to anyone reading the report, and it exists
nowhere else.

This tool finds those and writes them down.

## What it produces

**`gap_report.md`** — what the model has and what it lacks, scored against
sixteen things an ontology needs, plus the specific findings.

**`ontology.yaml`** — a draft ontology with the mechanical parts filled in and
the judgement calls left as TODO.

## Quick start

```bash
git clone https://github.com/<you>/pbi-ontology-gap
cd pbi-ontology-gap
python pbi_to_ontology.py examples/sample-model.bim --out-dir examples
```

Python 3.8 or later. Standard library only, nothing to install.

The example model is synthetic and deliberately contains the interesting cases:
a role playing dimension, an inactive relationship, two measures with identical
logic under different names, and one measure that skips the filter its siblings
all apply.

## What it checks

| Check | Where it comes from |
|---|---|
| Classes, identifiers, typed properties | Structural, always available |
| Relationship direction and cardinality | Structural |
| Relationship names | Proposed from what each join points at |
| Grain of each table | Proposed from the dimensions it joins to |
| Value sets the measures depend on | Mined from DAX filter literals |
| Business rules | Mined from DAX, proposed as constraints |
| Measure dependency chains | Parsed from measure references |
| Class and measure descriptions | Present only if somebody filled them in |
| Hierarchy, subsumption | Not expressible in a tabular model |
| Cross system identity | Not expressible in a single model |

## What it finds, on the example model

**A measure that breaks its family's pattern.**

> `Margin Variance %` aggregates `Sales[Amount]`, `Sales[Cost]` with no filter on
> `OrderStatus`, while Cost of Sales, Net Revenue, Revenue and Total Revenue all
> apply one.

Four measures agree that only confirmed orders count. One does not, and returns
a number that does not mean what its name says. Nothing errors.

**The value set the numbers quietly depend on.**

```yaml
OrderStatus:
  values: ["Confirmed", "Shipped"]
  relied_on_by: [Cost of Sales, Net Revenue, Revenue, Total Revenue]
  closed: TODO can a new value appear in the source? who approves it?
```

If a new status appears in the source, no measure counts it and no error is
raised. The report tells you the one query that settles it.

**Two measures with identical logic under different names.** Somebody will
eventually ask which is correct.

**Power BI's own machinery, excluded.** Auto date/time creates a hidden date
table per date column. Left in, they inflate the table count and show up as
path ambiguities that are not real.

## Using it on your own model

The script reads a TMSL file, usually called `model.bim`. Three ways to get one:

1. **Tabular Editor 2** (free). File > Open > From DB, pick your running Power
   BI Desktop instance, then File > Save As > `model.bim`. Use Save As, not
   Save, which writes back to the live model.
2. **Power BI project format.** Save your report as `.pbip` in Desktop.
3. **An XMLA endpoint**, for a model published to a workspace.

Then:

```bash
python pbi_to_ontology.py model.bim --out-dir out
```

### Sharing the output

Model metadata is not data, but table names, measure names and DAX can still
give away business logic. There is a flag for that:

```bash
python pbi_to_ontology.py model.bim --out-dir out --anonymize
```

Every name, description and DAX literal is replaced. Every count, cardinality,
ambiguity and percentage survives, so the report still says what it found.

Add `*.bim` and `*.pbix` to your `.gitignore` before the first commit. The
usual way this leaks is someone committing the source file next to the tool.

## What it cannot do

Being clear about this matters more than the feature list.

**It cannot write a definition.** A machine saying "Revenue means OrderStatus
equals Confirmed" is restating the DAX in English. It adds no information and
nobody has agreed to it. Everything the tool generates is marked `proposed`.
An ontology is only worth something because a person stands behind it.

**The fact and dimension split is a heuristic**, based on which side of
relationships a table sits on. It will get unusual models wrong.

**Grain proposals can be wrong.** The tool only sees declared relationships, so
a column that behaves like a dimension with no dimension table behind it is
invisible. Where it spots one, it says so, but it cannot catch them all.

**The coded column list is candidates, not findings.** A model file holds no
data, so the tool can only flag names that look like codes.

**The relationship names are weak.** They are better than nothing and worse
than five minutes of your own time. Overwrite them.

## Licence

MIT. See `LICENSE`.
