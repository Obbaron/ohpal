---
title: Calculated columns
section: Data
order: 20
keywords: calculation, formula, derive, derived, expression, function, mean, std, cov, where, by, group, aggregate, overwrite, sqrt, log, brackets
---
# Calculated columns

**Add column ▸ Calculation** makes a column from a formula over other columns.

## The dialog

- **Create new column**: give it a name and, if you like, choose the column
  it should sit **after**.
- **Overwrite existing column**: replace a column's values with the formula's
  result.
- **Formula**: type it, or build it from the **Functions** and **Columns**
  menus. The line under the box turns green when the formula is valid and
  explains what is wrong when it is not.

Press **Run** to add the column.

## Writing a formula

Refer to a column by its name in square brackets. Typing `[` offers the list
of columns.

```
[Meltpool] / [Output power]
```

Use `+ - * /` and parentheses as usual. Dividing by zero gives an empty cell,
not an error.

### Row-by-row functions

`abs`, `sqrt`, `log`, `log10`, `exp`, `sin`, `cos` work on each row:

```
sqrt([X] * [X] + [Y] * [Y])
```

### Summary functions

`mean`, `median`, `std`, `var`, `sum`, `min`, `max`, `count`, `n_unique`,
`first`, `last` and `cov` reduce a column to one value. On their own they use
all the rows and repeat that value on every row:

```
[Meltpool] - mean([Meltpool])
```

`cov` is the coefficient of variation: standard deviation divided by mean.

### Per group: `by`

Add `by [column]` after a summary function to compute it within each group:
per part, per layer, or both.

```
mean([Meltpool]) by [part_id]
cov([Meltpool]) by [part_id, layer]
```

Every row gets the value of its own group.

### Conditions: `where`

`where(condition, a, b)` picks `a` on rows where the condition holds and `b`
elsewhere. Text goes in double quotes:

```
where([Z] > 0.5, "high", "low")
```

Written after a value, `where` restricts which rows a summary uses:

```
mean([Meltpool] where [side] == "A") by [part_id]
```

Conditions use `== != < <= > >=` with `and`, `or`, `not`.

## Good to know

- A calculated column is recomputed for whichever layers are in use. A summary
  on the Data tab covers the layer on screen; in a plot or export it covers
  that plot's or export's layers.
- A later column can use an earlier one.
- If a formula's column is renamed, the formula follows.
- For a quick per-part mean, CoV and the like, [Parts ▸ Per-part
  calculation](help:parts) writes the formula for you.

## See also

- [Label columns](help:columns-label)
- [Filters](help:filters)
