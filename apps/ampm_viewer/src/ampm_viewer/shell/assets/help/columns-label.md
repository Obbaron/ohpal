---
title: Label columns
section: Data
order: 30
keywords: label, group, rule, condition, tag, region, category, default, if, else
---
# Label columns

**Add column ▸ Label** tags each row with a piece of text, chosen by rules you
write. Use it to mark regions of the plate, power bands, or good and bad
parts: anything you then want to colour, group or filter by.

## Making one

1. Give the column a name.
2. For each rule, write a **condition** and the **label** rows matching it
   should get. **Add rule** adds another.
3. Under **Otherwise**, set the label for rows that match no rule.

```
[X] > 30 and [Y] < -21          →  corner
[X] > 30                        →  right edge
(default)                       →  rest
```

Rules are tried from the top and the **first match wins**, so put the most
specific rule first. In the example a point in the corner is labelled
*corner*, not *right edge*.

## Conditions

Conditions are written like the ones in [filters](help:filters): columns in
square brackets, comparisons (`== != < <= > >=`), joined with `and`, `or`,
`not`. A chained range works too: `0 < [Z] < 1`.

## Using the label

- **Colour by** it in a scatter plot to see the groups.
- Use it as the **Category** of a bar chart or the **Group by** of a CoV
  summary.
- Use it after `by` in a [calculation](help:columns-calculation):
  `mean([Meltpool]) by [region]`.
