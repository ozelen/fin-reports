import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import api from "../api";

const currency = (v, code = "EUR") =>
  new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: code || "EUR",
  }).format(v || 0);

const PERIODS = [
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
  { value: "year", label: "Yearly" },
];
const KINDS = [
  { value: "spend", label: "Spend" },
  { value: "income", label: "Income" },
  { value: "save", label: "Save" },
];

const BLANK = {
  tag: "",
  period: "month",
  kind: "spend",
  amount: "",
  account: "",
  is_active: true,
};

const todayIso = () => new Date().toISOString().slice(0, 10);

export default function Budgets() {
  const [status, setStatus] = useState(null);
  const [tags, setTags] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [asOf, setAsOf] = useState(todayIso);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);

  const load = async () => {
    const [st, tg, ac] = await Promise.all([
      api.get("/budgets/status/", { params: { as_of: asOf } }),
      api.get("/tags/", { params: { page_size: 200 } }),
      api.get("/accounts/", { params: { page_size: 200 } }),
    ]);
    setStatus(st.data);
    setTags(tg.data.results);
    setAccounts(ac.data.results);
  };

  useEffect(() => {
    load();
  }, [asOf]);

  const openNew = () => {
    setEditing(null);
    setForm(BLANK);
    setOpen(true);
  };

  const openEdit = (row) => {
    setEditing(row);
    setForm({
      tag: row.tag,
      period: row.period,
      kind: row.kind,
      amount: row.amount,
      account: row.account || "",
      is_active: row.is_active,
    });
    setOpen(true);
  };

  const payload = () => ({
    tag: form.tag,
    period: form.period,
    kind: form.kind,
    amount: form.amount,
    account: form.account || null,
    is_active: form.is_active,
  });

  const save = async () => {
    if (editing) await api.patch(`/budgets/${editing.id}/`, payload());
    else await api.post("/budgets/", payload());
    setOpen(false);
    load();
  };

  const remove = async (row) => {
    await api.delete(`/budgets/${row.id}/`);
    load();
  };

  const lines = status?.budgets || [];

  return (
    <Box>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mb: 2, flexWrap: "wrap", gap: 2 }}
      >
        <TextField
          size="small"
          label="As of"
          type="date"
          value={asOf}
          onChange={(e) => setAsOf(e.target.value)}
          InputLabelProps={{ shrink: true }}
          sx={{ width: 170 }}
        />
        <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          New budget
        </Button>
      </Stack>

      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", mb: 2 }} useFlexGap>
        <Kpi label="Current balance" value={currency(status?.current_balance)} />
        <Kpi
          label="Remaining in"
          value={currency(status?.remaining_income)}
          color="success.main"
        />
        <Kpi
          label="Remaining out"
          value={currency(status?.remaining_spend)}
          color="error.main"
        />
        <Kpi
          label="Projected"
          value={currency(status?.projected_balance)}
          color="text.primary"
        />
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 2 }}>
        Projected if remaining budgeted amounts still land — weekly and monthly leftovers
        are summed together.
      </Typography>

      <Stack spacing={1}>
        {lines.map((row) => (
          <BudgetRow
            key={row.id}
            row={row}
            onEdit={() => openEdit(row)}
            onDelete={() => remove(row)}
          />
        ))}
        {lines.length === 0 && (
          <Typography color="text.secondary">No budgets yet.</Typography>
        )}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>{editing ? "Edit budget" : "New budget"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              select
              label="Tag"
              value={form.tag}
              onChange={(e) => setForm({ ...form, tag: e.target.value })}
              fullWidth
            >
              {tags.map((t) => (
                <MenuItem key={t.id} value={t.id}>
                  {t.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Period"
              value={form.period}
              onChange={(e) => setForm({ ...form, period: e.target.value })}
              fullWidth
            >
              {PERIODS.map((p) => (
                <MenuItem key={p.value} value={p.value}>
                  {p.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Kind"
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}
              fullWidth
            >
              {KINDS.map((k) => (
                <MenuItem key={k.value} value={k.value}>
                  {k.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Amount (EUR)"
              type="number"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              fullWidth
            />
            <TextField
              select
              label="Account"
              value={form.account}
              onChange={(e) => setForm({ ...form, account: e.target.value })}
              fullWidth
            >
              <MenuItem value="">All accounts</MenuItem>
              {accounts.map((a) => (
                <MenuItem key={a.id} value={a.id}>
                  {a.name}
                </MenuItem>
              ))}
            </TextField>
            <FormControlLabel
              control={
                <Switch
                  checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={save}
            disabled={!form.tag || form.amount === ""}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function BudgetRow({ row, onEdit, onDelete }) {
  const ratio = row.ratio == null ? 0 : Math.min(row.ratio, 1);
  const over = row.kind === "spend" && row.ratio != null && row.ratio > 1;
  const behind =
    (row.kind === "save" || row.kind === "income") &&
    row.ratio != null &&
    row.ratio < 1;
  const barColor = over ? "error" : behind ? "warning" : "success";
  const txParams = new URLSearchParams({
    tags: String(row.tag),
    date_from: row.period_start,
    date_to: row.period_end,
  });
  if (row.account) txParams.set("account", String(row.account));
  const periodLabel = PERIODS.find((p) => p.value === row.period)?.label || row.period;
  const kindLabel = KINDS.find((k) => k.value === row.kind)?.label || row.kind;

  return (
    <Paper
      variant="outlined"
      sx={{ p: 1.5, opacity: row.is_active ? 1 : 0.55 }}
    >
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 1 }}>
        <Chip
          label={row.tag_name}
          sx={{ bgcolor: row.tag_color, color: "#fff", fontWeight: 600 }}
        />
        <Chip size="small" variant="outlined" label={kindLabel} />
        <Chip size="small" variant="outlined" label={periodLabel} />
        {row.account_label && (
          <Chip size="small" variant="outlined" label={row.account_label} />
        )}
        {!row.is_active && <Chip size="small" label="Paused" />}
        <Typography variant="body2" sx={{ flexGrow: 1, textAlign: "right" }}>
          {currency(row.actual)} / {currency(row.amount)}
        </Typography>
        <Button
          size="small"
          component={RouterLink}
          to={`/transactions?${txParams}`}
        >
          View
        </Button>
        <IconButton size="small" onClick={onEdit}>
          <EditIcon fontSize="small" />
        </IconButton>
        <IconButton size="small" color="error" onClick={onDelete}>
          <DeleteIcon fontSize="small" />
        </IconButton>
      </Stack>
      <LinearProgress
        variant="determinate"
        value={ratio * 100}
        color={barColor}
        sx={{ height: 8, borderRadius: 1 }}
      />
    </Paper>
  );
}

function Kpi({ label, value, color }) {
  return (
    <Paper variant="outlined" sx={{ px: 3, py: 1.5, flex: 1, minWidth: 150 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" sx={{ color, fontWeight: 700 }}>
        {value}
      </Typography>
    </Paper>
  );
}
