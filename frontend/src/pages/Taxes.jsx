import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import SettingsIcon from "@mui/icons-material/Settings";
import api from "../api";
import TagMultiSelect from "../components/TagMultiSelect";

import { money as currency } from "../money";

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 6 }, (_, i) => CURRENT_YEAR - 2 + i);
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
const SOURCE_LABEL = {
  calendar: "Working days",
  invoice: "Invoice",
  override: "Override",
  bank: "Bank",
  mixed: "Mixed",
};

const RECEIVED_SOURCES = new Set(["bank", "invoice"]);
const EXPECTED_SOURCES = new Set(["calendar", "override"]);

function forecastTotals(est) {
  const received = {};
  const expected = {};
  let receivedTotal = 0;
  let expectedTotal = 0;
  for (const row of est.months || []) {
    if (est.clients?.length) {
      for (const c of est.clients) {
        const cell = row.by_client?.[String(c.id)];
        const amt = Number(cell?.amount || 0);
        if (!amt) continue;
        if (RECEIVED_SOURCES.has(cell?.source)) {
          received[c.id] = (received[c.id] || 0) + amt;
          receivedTotal += amt;
        } else if (EXPECTED_SOURCES.has(cell?.source)) {
          expected[c.id] = (expected[c.id] || 0) + amt;
          expectedTotal += amt;
        }
      }
    } else if (row.bucket === "ytd") {
      receivedTotal += Number(row.amount || 0);
    } else {
      expectedTotal += Number(row.amount || 0);
    }
  }
  return { received, expected, receivedTotal, expectedTotal };
}

function Kpi({ label, value, color, hint }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, minWidth: 160, flexGrow: 1 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" sx={{ fontWeight: 700, color }}>
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

export default function Taxes() {
  const [year, setYear] = useState(CURRENT_YEAR);
  const [est, setEst] = useState(null);
  const [profile, setProfile] = useState(null);
  const [tags, setTags] = useState([]);
  const [settings, setSettings] = useState(false);
  const [form, setForm] = useState(null);
  const [hoursDraft, setHoursDraft] = useState({});

  const load = async () => {
    const [e, p, t] = await Promise.all([
      api.get("/tax/estimate/", { params: { year } }),
      api.get("/tax/profile/"),
      api.get("/tags/", { params: { page_size: 200 } }),
    ]);
    setEst(e.data);
    setProfile(p.data);
    setTags(t.data.results);
    setHoursDraft({});
  };

  useEffect(() => {
    load();
  }, [year]);

  const openSettings = () => {
    setForm({
      withholding_rate: profile.withholding_rate,
      simplificada: profile.simplificada,
      income_from: profile.income_from,
      hourly_rate: profile.hourly_rate ?? 30,
      hours_per_day: profile.hours_per_day ?? 8,
      ss_mode: profile.ss_mode,
      ss_cuota_override: profile.ss_cuota_override ?? "",
      new_autonomo_start: profile.new_autonomo_start || "",
      planned_income_override: profile.planned_income_override ?? "",
      deductible_tags: profile.deductible_tags || [],
    });
    setSettings(true);
  };

  const save = async () => {
    await api.patch("/tax/profile/", {
      ...form,
      hourly_rate: form.hourly_rate === "" ? 30 : form.hourly_rate,
      hours_per_day: form.hours_per_day === "" ? 8 : form.hours_per_day,
      ss_cuota_override: form.ss_cuota_override === "" ? null : form.ss_cuota_override,
      new_autonomo_start: form.new_autonomo_start || null,
      planned_income_override:
        form.planned_income_override === "" ? null : form.planned_income_override,
    });
    setSettings(false);
    load();
  };

  const saveMonthHours = async (row) => {
    const typed = hoursDraft[row.key];
    if (typed === undefined) return;
    const baseline = row.invoice_hours ?? row.calendar_hours;
    const next = { ...(profile.hours_overrides || {}) };
    if (typed === "" || Number(typed) === Number(baseline)) delete next[row.key];
    else next[row.key] = Number(typed);
    await api.patch("/tax/profile/", { hours_overrides: next });
    load();
  };

  return (
    <Box>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mb: 2, flexWrap: "wrap", gap: 2 }}
      >
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Taxes
        </Typography>
        <Stack direction="row" spacing={1}>
          <TextField
            select
            size="small"
            label="Year"
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            sx={{ width: 120 }}
          >
            {YEARS.map((y) => (
              <MenuItem key={y} value={y}>
                {y}
              </MenuItem>
            ))}
          </TextField>
          <Button startIcon={<SettingsIcon />} onClick={openSettings} disabled={!profile}>
            Settings
          </Button>
        </Stack>
      </Stack>

      {est?.disclaimer && (
        <Alert severity="info" sx={{ mb: 2 }}>
          {est.disclaimer}
        </Alert>
      )}

      {est && (
        <>
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", mb: 2 }} useFlexGap>
            <Kpi
              label="Earned so far"
              value={currency(est.income.ytd)}
              color="success.main"
              hint="Bank + invoices already in this year"
            />
            <Kpi
              label="Still expected"
              value={currency(est.income.planned)}
              hint="Rest of this year on the calendar"
            />
            <Kpi
              label="Taxable profit"
              value={currency(est.rendimiento_neto)}
              hint="Year income − RETA − deductible spends − 5% simplificada"
            />
            <Kpi
              label="Still to set aside"
              value={currency(est.set_aside)}
              color="error.main"
              hint="RETA cuotas + modelo 130 still unpaid this year"
            />
          </Stack>

          <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
            <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                Income & expenses
              </Typography>
              <Row label="Earned so far" value={currency(est.income.ytd)} />
              <Row
                label={est.income.override ? "Still expected (override)" : "Still expected"}
                value={currency(est.income.planned)}
              />
              <Row label="Deductible expenses YTD" value={currency(est.expenses.ytd)} />
              <Row label="RETA (year)" value={currency(est.expenses.ss)} />
              <Row label="Simplificada 5%" value={currency(est.simplificada)} />
            </Paper>
            <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                Seguridad Social (RETA)
              </Typography>
              <Row label="Monthly cuota" value={currency(est.ss.monthly_cuota)} />
              <Row label="Paid this year" value={currency(est.ss.paid)} />
              <Row label="Remaining" value={currency(est.ss.remaining)} />
              {est.ss.source === "last_paid" && (
                <Typography variant="caption" color="text.secondary">
                  From last TGSS cargo. RETA table min {currency(est.ss.statutory_min)}
                  /month at this net.
                </Typography>
              )}
              {est.ss.tarifa_plana && (
                <Chip size="small" label="Tarifa plana 80€" sx={{ mt: 1 }} />
              )}
            </Paper>
            <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                IRPF
              </Typography>
              <Row label="Next 130 (after quarter)" value={currency(est.modelo_130.this_installment)} />
              <Row label="130 paid" value={currency(est.modelo_130.paid)} />
              <Row label="130 remaining" value={currency(est.modelo_130.remaining)} />
              <Row label="Annual IRPF (estatal)" value={currency(est.irpf_annual.gross)} />
              <Row
                label="Renta remainder"
                value={currency(est.irpf_annual.renta_remainder)}
              />
            </Paper>
          </Stack>

          <Paper variant="outlined" sx={{ p: 2, mb: 2, overflowX: "auto" }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
              Salary forecast
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              {est.clients?.length
                ? "One column per client with invoices, matched salary, or an active engagement this year. Issued invoices and bank payments replace the calendar."
                : `${est.income.hourly_rate} €/h × ${est.income.hours_per_day}h × Mon–Fri.`}
              {" "}
              Edit hours to override hour-billed calendar months.
            </Typography>
            <ForecastTable
              est={est}
              hoursDraft={hoursDraft}
              setHoursDraft={setHoursDraft}
              saveMonthHours={saveMonthHours}
            />
          </Paper>

          <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
              Modelo 130 (pago fraccionado)
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              20% of (quarter income − RETA − deductible business spends), due the 20th
              after the quarter. Pick tags under Settings. Paid quarters stay as the bank cargo.
            </Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Quarter</TableCell>
                  <TableCell>Months</TableCell>
                  <TableCell>Due</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Income</TableCell>
                  <TableCell align="right">Gastos</TableCell>
                  <TableCell align="right">Amount</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {est.modelo_130.quarters?.map((q) => (
                  <TableRow key={q.quarter}>
                    <TableCell>Q{q.quarter}</TableCell>
                    <TableCell>{q.period}</TableCell>
                    <TableCell>{q.due}</TableCell>
                    <TableCell>
                      <Chip size="small" variant="outlined" label={q.status} />
                    </TableCell>
                    <TableCell align="right">{currency(q.income)}</TableCell>
                    <TableCell align="right">{currency(q.gastos)}</TableCell>
                    <TableCell align="right">{currency(q.amount)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>

          <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
              Tax payments found
            </Typography>
            {est.paid_payments?.length ? (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Date</TableCell>
                    <TableCell>Name</TableCell>
                    <TableCell>Kind</TableCell>
                    <TableCell align="right">Amount</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {est.paid_payments.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell>{p.date}</TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          component={RouterLink}
                          to={`/transactions?date_from=${p.date}&date_to=${p.date}`}
                          sx={{ textTransform: "none" }}
                        >
                          {p.name}
                        </Button>
                      </TableCell>
                      <TableCell>{p.kind}</TableCell>
                      <TableCell align="right">{currency(p.amount)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Typography variant="body2" color="text.secondary">
                No TGSS / IRPF / AEAT payments found on imported statements for {year}.
              </Typography>
            )}
          </Paper>

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="center"
              sx={{ mb: 1 }}
            >
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                Remaining tax payments
              </Typography>
              <Button size="small" component={RouterLink} to="/transactions/recurring">
                Manage recurrences
              </Button>
            </Stack>
            {est.remaining_payments?.length ? (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Date</TableCell>
                    <TableCell>Name</TableCell>
                    <TableCell>Kind</TableCell>
                    <TableCell align="right">Amount</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {est.remaining_payments.map((p, i) => (
                    <TableRow key={`${p.kind}-${p.date}-${i}`}>
                      <TableCell>{p.date}</TableCell>
                      <TableCell>{p.name}</TableCell>
                      <TableCell>{p.kind}</TableCell>
                      <TableCell align="right">{currency(p.amount)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Nothing left to pay this year.
              </Typography>
            )}
          </Paper>
        </>
      )}

      <Dialog open={settings} onClose={() => setSettings(false)} fullWidth maxWidth="sm">
        <DialogTitle>Tax settings</DialogTitle>
        <DialogContent>
          {form && (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField
                select
                label="Income source"
                value={form.income_from}
                onChange={(e) => setForm({ ...form, income_from: e.target.value })}
              >
                <MenuItem value="hours">Hourly × working days</MenuItem>
                <MenuItem value="invoices">Issued invoices only</MenuItem>
                <MenuItem value="tags">Bank income (all inflows)</MenuItem>
              </TextField>
              <Stack direction="row" spacing={2}>
                <TextField
                  label="Hourly rate (€)"
                  type="number"
                  value={form.hourly_rate}
                  onChange={(e) => setForm({ ...form, hourly_rate: e.target.value })}
                  fullWidth
                />
                <TextField
                  label="Hours / day"
                  type="number"
                  value={form.hours_per_day}
                  onChange={(e) => setForm({ ...form, hours_per_day: e.target.value })}
                  fullWidth
                />
              </Stack>
              <TextField
                label="IRPF withholding % on invoices"
                type="number"
                value={form.withholding_rate}
                onChange={(e) => setForm({ ...form, withholding_rate: e.target.value })}
                helperText="0 if clients do not withhold; 7 first years / 15 standard"
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={form.simplificada}
                    onChange={(e) => setForm({ ...form, simplificada: e.target.checked })}
                  />
                }
                label="Estimación directa simplificada (5%, cap €2,000)"
              />
              <TextField
                select
                label="Cuota mode"
                value={form.ss_mode}
                onChange={(e) => setForm({ ...form, ss_mode: e.target.value })}
              >
                <MenuItem value="table">Last paid cuota (fallback: RETA table)</MenuItem>
                <MenuItem value="fixed">Fixed monthly cuota</MenuItem>
              </TextField>
              {form.ss_mode === "fixed" && (
                <TextField
                  label="Monthly cuota"
                  type="number"
                  value={form.ss_cuota_override}
                  onChange={(e) => setForm({ ...form, ss_cuota_override: e.target.value })}
                />
              )}
              <TextField
                label="New autónomo start (tarifa plana)"
                type="date"
                value={form.new_autonomo_start}
                onChange={(e) => setForm({ ...form, new_autonomo_start: e.target.value })}
                InputLabelProps={{ shrink: true }}
              />
              <TextField
                label="Planned income override (rest of year)"
                type="number"
                value={form.planned_income_override}
                onChange={(e) =>
                  setForm({ ...form, planned_income_override: e.target.value })
                }
                helperText="Leave empty to use the month grid"
              />
              <TagMultiSelect
                tags={tags}
                value={form.deductible_tags}
                onChange={(v) => setForm({ ...form, deductible_tags: v })}
                label="Deductible expense tags"
              />
              <Typography variant="caption" color="text.secondary">
                These tags cut modelo 130 by 20% of the spend. Typical: gestor, office,
                ai, clouds, internet, paperwork, devices. Skip groceries, family, and
                mixed travel unless your gestor treats them as activity costs.
              </Typography>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSettings(false)}>Cancel</Button>
          <Button variant="contained" onClick={save}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function ForecastTable({ est, hoursDraft, setHoursDraft, saveMonthHours }) {
  const totals = forecastTotals(est);
  const clients = est.clients || [];
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Month</TableCell>
          <TableCell align="right">Days</TableCell>
          <TableCell align="right">Hours</TableCell>
          {clients.map((c) => (
            <TableCell key={c.id} align="right">
              {c.short_name || c.name}
            </TableCell>
          ))}
          <TableCell>Source</TableCell>
          <TableCell align="right">Total</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {est.months?.map((row) => (
          <TableRow key={row.key} sx={{ opacity: row.bucket === "planned" ? 1 : 0.95 }}>
            <TableCell>{MONTHS[row.month - 1]}</TableCell>
            <TableCell align="right">{row.working_days}</TableCell>
            <TableCell align="right" sx={{ width: 110 }}>
              <TextField
                size="small"
                type="number"
                value={hoursDraft[row.key] ?? row.hours}
                onChange={(e) => setHoursDraft({ ...hoursDraft, [row.key]: e.target.value })}
                onBlur={() => saveMonthHours(row)}
                inputProps={{ step: 1, min: 0, style: { textAlign: "right" } }}
                variant="standard"
              />
            </TableCell>
            {clients.map((c) => (
              <TableCell key={c.id} align="right">
                {currency(row.by_client?.[String(c.id)]?.amount || 0)}
              </TableCell>
            ))}
            <TableCell>
              <Chip size="small" variant="outlined" label={SOURCE_LABEL[row.source] || row.source} />
            </TableCell>
            <TableCell align="right">{currency(row.amount)}</TableCell>
          </TableRow>
        ))}
        <TableRow>
          <TableCell sx={{ fontWeight: 700 }} colSpan={3}>
            Received
          </TableCell>
          {clients.map((c) => (
            <TableCell key={c.id} align="right" sx={{ fontWeight: 700 }}>
              {currency(totals.received[c.id] || 0)}
            </TableCell>
          ))}
          <TableCell>
            <Chip size="small" variant="outlined" label="Bank + invoice" />
          </TableCell>
          <TableCell align="right" sx={{ fontWeight: 700 }}>
            {currency(totals.receivedTotal)}
          </TableCell>
        </TableRow>
        <TableRow>
          <TableCell sx={{ fontWeight: 700 }} colSpan={3}>
            Expected
          </TableCell>
          {clients.map((c) => (
            <TableCell key={c.id} align="right" sx={{ fontWeight: 700 }}>
              {currency(totals.expected[c.id] || 0)}
            </TableCell>
          ))}
          <TableCell>
            <Chip size="small" variant="outlined" label="Calendar" />
          </TableCell>
          <TableCell align="right" sx={{ fontWeight: 700 }}>
            {currency(totals.expectedTotal)}
          </TableCell>
        </TableRow>
        <TableRow>
          <TableCell sx={{ fontWeight: 700 }} colSpan={3}>
            Year
          </TableCell>
          {clients.map((c) => (
            <TableCell key={c.id} align="right" sx={{ fontWeight: 700 }}>
              {currency((totals.received[c.id] || 0) + (totals.expected[c.id] || 0))}
            </TableCell>
          ))}
          <TableCell />
          <TableCell align="right" sx={{ fontWeight: 700 }}>
            {currency(totals.receivedTotal + totals.expectedTotal)}
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>
  );
}

function Row({ label, value }) {
  return (
    <Stack direction="row" justifyContent="space-between" sx={{ py: 0.4 }}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Stack>
  );
}
