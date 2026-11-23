# Ontology gap report: Sample Sales Model

What this semantic model already encodes, and what an ontology needs that
it structurally cannot hold.

**5 of 16 present, 5 partial, 6 absent.**

| What an ontology needs | Status | Evidence |
|---|---|---|
| Classes identified | present | 7 tables classified |
| Class identifiers | partial | 5 of 7 have one |
| Properties typed | present | 31 columns with data types |
| Class descriptions | partial | 1 of 7 filled, 14% |
| Property descriptions | partial | 1 of 31 filled, 3% |
| Class hierarchy, subsumption | absent | tabular models have no inheritance, nothing to extract |
| Named relationships | absent | Power BI relationships are unnamed column joins |
| Relationship direction | present | 8 relationships |
| Relationship cardinality | present | declared on every relationship |
| Unambiguous paths | partial | 5 ambiguity flags, see below |
| Explicit grain | absent | implied by the table, never stated |
| Measures with a formula | present | 11 measures |
| Measure definitions in business language | partial | 1 of 11 described, 9% |
| Coded value meanings | absent | 5 columns look coded, the file holds no data |
| Business rules and constraints | absent | 7 found hiding inside DAX, none declared |
| Cross-system identity | absent | one model is one system's view |

## Model at a glance

- Tables: 7
- Columns: 31, of which 1 hidden
- Relationships: 8
- Measures: 11

**3 auto-generated date tables excluded from every count above.**
Power BI creates a hidden date table for each date column when the
"Auto date/time" option is on. They are machinery, not business entities.
Worth knowing separately: that option bloats the model and gets in the way
of proper time intelligence, so it is usually turned off in favour of a
real date dimension. That is a modelling note, not an ontology gap.

## 1. Undeclared business rules, found inside DAX

Each line below is a rule that decides which rows count. It is load-bearing,
it is invisible to anyone reading the report, and it is written down nowhere
except inside one measure. Every one of these belongs in the ontology.

| Measure | Rule found in its logic |
|---|---|
| Sales[Revenue] | `[OrderStatus] = "Confirmed"` |
| Sales[Total Revenue] | `[OrderStatus] = "Confirmed"` |
| Sales[Net Revenue] | `[OrderStatus] = "Confirmed"` |
| Sales[Net Revenue] | `[DiscontinuedFlag] = 0` |
| Sales[Cost of Sales] | `[OrderStatus] IN {"Confirmed", "Shipped"}` |
| Sales[Shipped Revenue] | `USERELATIONSHIP, activates an inactive relationship` |
| Sales[FY24 Baseline] | `hardcoded year 2024` |

## 2. Path ambiguity

Every item here is a place where more than one answer is possible and
somebody already made a silent choice. An ontology has to make the choice
explicit, which is why these are Phase 3 work and not trivia.

**2 inactive relationships.** An alternate path exists and was turned off:
- Sales.ShipDate to Date.DateKey
- Employee.ManagerKey to Employee.EmployeeKey

**1 role-playing dimension.** The same two tables joined more than once.
Physically one table, ontologically two different relationships:
- Sales to Date, via OrderDate, ShipDate

**1 bidirectional filter.** Filter flows both ways, which
makes the meaning of a number depend on what else is on the page:
- Budget to Customer

**1 many-to-many relationship.** Usually a sign that an
entity has not been resolved to a single identity:
- Budget to Customer

## 3. Measures that skip their family's filter

A measure that aggregates the same source columns as its siblings but
applies none of their filters usually returns a number that does not mean
what its name says. Each of these needs a human to confirm whether it is
deliberate.

- **Margin Variance %** aggregates Sales[Amount], Sales[Cost] with no filter on `OrderStatus`, while Cost of Sales, Net Revenue, Revenue, Total Revenue all apply one.

## 4. Value sets the numbers depend on

These are the literals the model compares against. A value outside the
list is silently excluded with no error, so each list needs an owner and
a rule about what happens when a new value appears.

| Column | Values the model knows about | Measures relying on it |
|---|---|---|
| `OrderStatus` | Confirmed, Shipped | 4 |

## 5. Competing definitions

Measures with identical logic under different names. Somebody will
eventually ask which one is correct:
- Sales[Revenue], Sales[Total Revenue]

## 6. Missing definitions

1 of 7 tables and 1 of 11 measures carry a description.

Measures with no description, which means their meaning exists only in DAX:
- Sales[Revenue]
- Sales[Total Revenue]
- Sales[Cost of Sales]
- Sales[Gross Margin]
- Sales[Gross Margin %]
- Sales[Margin Variance %]
- Sales[Shipped Revenue]
- Sales[FY24 Baseline]
- Sales[Order Count]
- Budget[Budget Amount]

## 7. Columns that look coded

This file contains no data, so these are candidates to go and check, not
findings. Each one that does hold codes needs its values defined in words.

- Customer[SegmentCode]
- Product[DiscontinuedFlag]
- Employee[RegionCode]
- Sales[OrderStatus]
- Budget[SegmentCode]

## 8. What cannot be extracted at all

Not a shortcoming of this script. A tabular model has no way to express these.

- **Hierarchy.** No inheritance, so a rule true of several classes must be
  restated on each one instead of declared once on a parent.
- **Relationship meaning.** Direction and cardinality are there. What the
  link means is not.
- **Constraints.** No equivalent of a business rule. Row level security is
  access control, not semantics.
- **Grain, stated.** Implied by the table, never written down.
- **Cross-system identity.** One model is one system's view of the world.

## Sizing

- Definitions to write: 6 classes, 10 measures
- Relationships to name and give meaning: 8
- Rules to declare properly: 7 already found in DAX, plus whatever is not in DAX
- Ambiguities to resolve: 5
- Coded columns to check: 5

Roughly **24 items** need a human decision before this domain has a
certified semantic foundation. That number is the scope of the work, and
it came from a model that already exists rather than from a guess.
