import { Grid, MenuItem, TextField } from "@mui/material";

const QUARTERS = [
  { value: "", label: "Any" },
  { value: "this", label: "This quarter" },
  { value: "prev", label: "Previous quarter" },
  { value: "Q1", label: "Q1" },
  { value: "Q2", label: "Q2" },
  { value: "Q3", label: "Q3" },
  { value: "Q4", label: "Q4" },
];

/**
 * Editor for the shared "criteria" object (kind, keyword, counterparty,
 * quarter/year, date range, amount range). Emits a plain object with only the
 * set keys.
 */
export default function CriteriaFields({ value, onChange }) {
  const c = value || {};
  const set = (key) => (e) => {
    const next = { ...c };
    const v = e.target.value;
    if (v === "" || v == null) delete next[key];
    else next[key] = v;
    onChange(next);
  };

  return (
    <Grid container spacing={2}>
      <Grid item xs={6} sm={4}>
        <TextField
          select
          fullWidth
          size="small"
          label="Type"
          value={c.kind || ""}
          onChange={set("kind")}
        >
          <MenuItem value="">Any</MenuItem>
          <MenuItem value="income">Income</MenuItem>
          <MenuItem value="expense">Expense</MenuItem>
        </TextField>
      </Grid>
      <Grid item xs={6} sm={8}>
        <TextField
          fullWidth
          size="small"
          label="Keyword (concept)"
          value={c.keyword || ""}
          onChange={set("keyword")}
        />
      </Grid>
      <Grid item xs={12} sm={12}>
        <TextField
          fullWidth
          size="small"
          label="Counterparty contains"
          value={c.counterparty || ""}
          onChange={set("counterparty")}
        />
      </Grid>
      <Grid item xs={6} sm={4}>
        <TextField
          select
          fullWidth
          size="small"
          label="Quarter"
          value={c.quarter || ""}
          onChange={set("quarter")}
        >
          {QUARTERS.map((q) => (
            <MenuItem key={q.value} value={q.value}>
              {q.label}
            </MenuItem>
          ))}
        </TextField>
      </Grid>
      <Grid item xs={6} sm={4}>
        <TextField
          fullWidth
          size="small"
          label="Year"
          type="number"
          value={c.year || ""}
          onChange={set("year")}
        />
      </Grid>
      <Grid item xs={6} sm={2}>
        <TextField
          fullWidth
          size="small"
          label="Min €"
          type="number"
          value={c.min_amount || ""}
          onChange={set("min_amount")}
        />
      </Grid>
      <Grid item xs={6} sm={2}>
        <TextField
          fullWidth
          size="small"
          label="Max €"
          type="number"
          value={c.max_amount || ""}
          onChange={set("max_amount")}
        />
      </Grid>
      <Grid item xs={6}>
        <TextField
          fullWidth
          size="small"
          label="From"
          type="date"
          value={c.date_from || ""}
          onChange={set("date_from")}
          InputLabelProps={{ shrink: true }}
        />
      </Grid>
      <Grid item xs={6}>
        <TextField
          fullWidth
          size="small"
          label="To"
          type="date"
          value={c.date_to || ""}
          onChange={set("date_to")}
          InputLabelProps={{ shrink: true }}
        />
      </Grid>
    </Grid>
  );
}
