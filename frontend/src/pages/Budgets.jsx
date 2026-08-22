import { useEffect, useMemo, useState } from "react";
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
import { DataGrid } from "@mui/x-data-grid";
import { BarChart } from "@mui/x-charts/BarChart";
import api from "../api";
import RecurrenceDialog from "../components/RecurrenceDialog";

const currency = (v, code = "EUR") =>
  new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: code || "EUR",
  }).format(v || 0);

const PERIODS = [
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
  { value: "quarter", label: "Quarterly" },
  { value: "year", label: "Yearly" },
];
const BUDGET_PERIODS = PERIODS.filter((p) => p.value !== "quarter");
const SCOPES = [
  { value: "month", label: "Month" },
  { value: "quarter", label: "Quarter" },
  { value: "year", label: "Year" },
];
const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
].map((label, i) => ({ value: i + 1, label }));
const QUARTERS = [
  { value: 1, label: "Q1" },
  { value: 2, label: "Q2" },
  { value: 3, label: "Q3" },
  { value: 4, label: "Q4" },
];
const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 8 }, (_, i) => CURRENT_YEAR - i);
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

const GROUP_LABEL = {
  salary: "Salary",
  tax: "Tax",
  recurring: "Recurring",
  budget: "Budget",
};
const periodLabel = (v) => PERIODS.find((p) => p.value === v)?.label || v;
const kindLabel = (v) => KINDS.find((k) => k.value === v)?.label || v;

export default function Budgets() {
  const [status, setStatus] = useState(null);
  const [tags, setTags] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [scope, setScope] = useState("month");
  const [year, setYear] = useState(CURRENT_YEAR);
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [quarter, setQuarter] = useState(Math.floor(new Date().getMonth() / 3) + 1);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [recOpen, setRecOpen] = useState(false);
  const [editingRec, setEditingRec] = useState(null);
  const [chartSalary, setChartSalary] = useState(true);
  const [chartTax, setChartTax] = useState(true);
  const [chartRecurring, setChartRecurring] = useState(true);
  const [chartBudget, setChartBudget] = useState(true);

  const load = async () => {
    const params = { year };
    if (scope === "month") params.month = month;
    if (scope === "quarter") params.quarter = quarter;
    const [st, tg, ac] = await Promise.all([
      api.get("/budgets/status/", { params }),
      api.get("/tags/", { params: { page_size: 200 } }),
      api.get("/accounts/", { params: { page_size: 200 } }),
    ]);
    setStatus(st.data);
    setTags(tg.data.results);
    setAccounts(ac.data.results);
  };

  useEffect(() => {
    load();
  }, [scope, year, month, quarter]);

  const openNew = () => {
    setEditing(null);
    setForm(BLANK);
    setOpen(true);
  };

  const openEdit = async (row) => {
    if (row.source === "recurrence") {
      const { data } = await api.get(`/recurrences/${row.recurrence_id}/`);
      setEditingRec(data);
      setRecOpen(true);
      return;
    }
    setEditing(row);
    const { data } = await api.get(`/budgets/${row.budget_id}/`);
    setForm({
      tag: data.tag,
      period: data.period,
      kind: data.kind,
      amount: data.amount,
      account: data.account || "",
      is_active: data.is_active,
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
    if (editing) await api.patch(`/budgets/${editing.budget_id}/`, payload());
    else await api.post("/budgets/", payload());
    setOpen(false);
    load();
  };

  const remove = async (row) => {
    if (row.source === "recurrence") {
      await api.delete(`/recurrences/${row.recurrence_id}/`);
    } else {
      await api.delete(`/budgets/${row.budget_id}/`);
    }
    load();
  };

  const lines = status?.budgets || [];
  const visible = useMemo(() => {
    const on = {
      salary: chartSalary,
      tax: chartTax,
      recurring: chartRecurring,
      budget: chartBudget,
    };
    return lines.filter((r) => on[r.group] !== false);
  }, [lines, chartSalary, chartTax, chartRecurring, chartBudget]);
  const chart = useMemo(() => {
    const rows = visible.filter(
      (r) => r.is_active && ((r.amount || 0) || (r.actual || 0)),
    );
    return {
      labels: rows.map((r) => r.name),
      planned: rows.map((r) => r.amount || 0),
      actual: rows.map((r) => r.actual || 0),
    };
  }, [visible]);

  const columns = [
    {
      field: "group",
      headerName: "Type",
      width: 120,
      renderCell: (p) => (
        <Chip size="small" variant="outlined" label={GROUP_LABEL[p.value] || p.value} />
      ),
    },
    {
      field: "name",
      headerName: "Name",
      flex: 1,
      minWidth: 180,
      renderCell: (p) => (
        <Stack direction="row" spacing={1} alignItems="center">
          {p.row.tag_name && (
            <Chip
              size="small"
              label={p.row.tag_name}
              sx={{ bgcolor: p.row.tag_color, color: "#fff", fontWeight: 600 }}
            />
          )}
          {(p.row.source === "recurrence" || p.row.source === "irpf") && (
            <Typography variant="body2">{p.value}</Typography>
          )}
        </Stack>
      ),
    },
    {
      field: "kind",
      headerName: "Kind",
      width: 110,
      valueGetter: (value) => kindLabel(value),
    },
    {
      field: "period",
      headerName: "Cadence",
      width: 120,
      valueGetter: (value) => periodLabel(value),
    },
    {
      field: "account_label",
      headerName: "Account",
      width: 140,
      valueGetter: (value) => value || "All",
    },
    {
      field: "amount",
      headerName: "Planned",
      width: 130,
      type: "number",
      renderCell: (p) => (
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {currency(p.value)}
        </Typography>
      ),
    },
    {
      field: "actual",
      headerName: "Actual",
      width: 130,
      type: "number",
      renderCell: (p) => {
        const over = p.row.kind === "spend" && (p.value || 0) > (p.row.amount || 0);
        const behind =
          (p.row.kind === "save" || p.row.kind === "income") &&
          (p.value || 0) < (p.row.amount || 0);
        return (
          <Typography
            variant="body2"
            sx={{
              fontWeight: 600,
              color: over ? "error.main" : behind ? "warning.main" : "success.main",
            }}
          >
            {currency(p.value)}
          </Typography>
        );
      },
    },
    {
      field: "is_active",
      headerName: "Active",
      width: 90,
      renderCell: (p) =>
        p.value ? "" : <Chip size="small" label="Paused" />,
    },
    {
      field: "actions",
      headerName: "",
      width: 160,
      sortable: false,
      filterable: false,
      renderCell: (p) => {
        if (p.row.source === "irpf") {
          return (
            <Button size="small" component={RouterLink} to="/taxes">
              View
            </Button>
          );
        }
        const params = new URLSearchParams();
        if (p.row.source === "recurrence") {
          params.set("recurrence", String(p.row.recurrence_id));
        } else {
          params.set("tags", String(p.row.tag));
          params.set("date_from", p.row.period_start);
          params.set("date_to", p.row.period_end);
          if (p.row.account) params.set("account", String(p.row.account));
        }
        return (
          <Stack direction="row" alignItems="center">
            <Button size="small" component={RouterLink} to={`/transactions?${params}`}>
              View
            </Button>
            <IconButton size="small" onClick={() => openEdit(p.row)}>
              <EditIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" color="error" onClick={() => remove(p.row)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Stack>
        );
      },
    },
  ];

  return (
    <Box>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mb: 2, flexWrap: "wrap", gap: 2 }}
      >
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
          <TextField
            select
            size="small"
            label="View"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            sx={{ minWidth: 130 }}
          >
            {SCOPES.map((s) => (
              <MenuItem key={s.value} value={s.value}>
                {s.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Year"
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            sx={{ minWidth: 110 }}
          >
            {YEARS.map((y) => (
              <MenuItem key={y} value={y}>
                {y}
              </MenuItem>
            ))}
          </TextField>
          {scope === "month" && (
            <TextField
              select
              size="small"
              label="Month"
              value={month}
              onChange={(e) => setMonth(Number(e.target.value))}
              sx={{ minWidth: 150 }}
            >
              {MONTHS.map((m) => (
                <MenuItem key={m.value} value={m.value}>
                  {m.label}
                </MenuItem>
              ))}
            </TextField>
          )}
          {scope === "quarter" && (
            <TextField
              select
              size="small"
              label="Quarter"
              value={quarter}
              onChange={(e) => setQuarter(Number(e.target.value))}
              sx={{ minWidth: 110 }}
            >
              {QUARTERS.map((q) => (
                <MenuItem key={q.value} value={q.value}>
                  {q.label}
                </MenuItem>
              ))}
            </TextField>
          )}
        </Stack>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          New budget
        </Button>
      </Stack>

      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", mb: 2 }} useFlexGap>
        <Kpi
          label="Available after tax"
          value={currency(status?.available_after_tax)}
          color={
            (status?.available_after_tax || 0) < 0 ? "error.main" : "success.main"
          }
          hint={`Keep ${currency(status?.tax_set_aside)} for unpaid RETA + 130`}
        />
        <Kpi
          label="Salary this period"
          value={currency(status?.salary)}
          color="success.main"
        />
        <Kpi
          label="Tax this period"
          value={currency(status?.tax)}
          color="error.main"
        />
        <Kpi
          label="After tax this period"
          value={currency(status?.after_tax)}
          color={
            (status?.after_tax || 0) < 0 ? "error.main" : "text.primary"
          }
        />
      </Stack>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          flexWrap="wrap"
          useFlexGap
          spacing={1}
          sx={{ mb: 1 }}
        >
          <Typography variant="subtitle2" color="text.secondary">
            Planned vs actual
          </Typography>
          <Stack direction="row" flexWrap="wrap">
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={chartSalary}
                  onChange={(e) => setChartSalary(e.target.checked)}
                />
              }
              label="Salary"
            />
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={chartTax}
                  onChange={(e) => setChartTax(e.target.checked)}
                />
              }
              label="Tax"
            />
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={chartRecurring}
                  onChange={(e) => setChartRecurring(e.target.checked)}
                />
              }
              label="Recurring"
            />
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={chartBudget}
                  onChange={(e) => setChartBudget(e.target.checked)}
                />
              }
              label="Budgets"
            />
          </Stack>
        </Stack>
        {chart.labels.length === 0 ? (
          <Typography color="text.secondary">No active lines to chart.</Typography>
        ) : (
          <BarChart
            layout="horizontal"
            height={Math.max(240, chart.labels.length * 34 + 60)}
            yAxis={[{ scaleType: "band", data: chart.labels, width: 120 }]}
            series={[
              { data: chart.planned, label: "Planned", color: "#1f4e78" },
              { data: chart.actual, label: "Actual", color: "#2e9e5b" },
            ]}
            margin={{ left: 130, right: 20, top: 20, bottom: 30 }}
            slotProps={{ legend: { position: { vertical: "top", horizontal: "right" } } }}
          />
        )}
      </Paper>

      <DataGrid
        autoHeight
        rows={visible}
        columns={columns}
        pageSizeOptions={[25, 50, 100]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        disableRowSelectionOnClick
        getRowClassName={(p) => (p.row.is_active ? "" : "row-paused")}
        sx={{
          bgcolor: "background.paper",
          "& .MuiDataGrid-cell": { py: 0.5 },
          "& .row-paused": { opacity: 0.55 },
        }}
      />

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
              {BUDGET_PERIODS.map((p) => (
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

      <RecurrenceDialog
        open={recOpen}
        recurrence={editingRec}
        tags={tags}
        accounts={accounts}
        onClose={() => {
          setRecOpen(false);
          setEditingRec(null);
        }}
        onSaved={() => {
          setRecOpen(false);
          setEditingRec(null);
          load();
        }}
      />
    </Box>
  );
}

function Kpi({ label, value, color, hint }) {
  return (
    <Paper variant="outlined" sx={{ px: 3, py: 1.5, flex: 1, minWidth: 150 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" sx={{ color, fontWeight: 700 }}>
        {value}
      </Typography>
      {hint && (
        <Typography variant="caption" color="text.secondary">
          {hint}
        </Typography>
      )}
    </Paper>
  );
}
