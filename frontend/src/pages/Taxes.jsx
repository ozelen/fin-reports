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

const currency = (v, code = "EUR") =>
  new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: code || "EUR",
  }).format(v || 0);

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 6 }, (_, i) => CURRENT_YEAR - 2 + i);

function Kpi({ label, value, color }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, minWidth: 160, flexGrow: 1 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" sx={{ fontWeight: 700, color }}>
        {value}
      </Typography>
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

  const load = async () => {
    const [e, p, t] = await Promise.all([
      api.get("/tax/estimate/", { params: { year } }),
      api.get("/tax/profile/"),
      api.get("/tags/", { params: { page_size: 200 } }),
    ]);
    setEst(e.data);
    setProfile(p.data);
    setTags(t.data.results);
  };

  useEffect(() => {
    load();
  }, [year]);

  const openSettings = () => {
    setForm({
      withholding_rate: profile.withholding_rate,
      simplificada: profile.simplificada,
      income_from: profile.income_from,
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
      ss_cuota_override: form.ss_cuota_override === "" ? null : form.ss_cuota_override,
      new_autonomo_start: form.new_autonomo_start || null,
      planned_income_override:
        form.planned_income_override === "" ? null : form.planned_income_override,
    });
    setSettings(false);
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
            <Kpi label="YTD income" value={currency(est.income.ytd)} color="success.main" />
            <Kpi label="Planned income" value={currency(est.income.planned)} />
            <Kpi label="Rendimiento neto" value={currency(est.rendimiento_neto)} />
            <Kpi
              label="Still to set aside"
              value={currency(est.set_aside)}
              color="error.main"
            />
          </Stack>

          <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
            <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                Income & expenses
              </Typography>
              <Row label="Income YTD" value={currency(est.income.ytd)} />
              <Row
                label={est.income.override ? "Planned (override)" : "Planned remaining"}
                value={currency(est.income.planned)}
              />
              <Row label="Deductible expenses YTD" value={currency(est.expenses.ytd)} />
              <Row label="Planned expenses" value={currency(est.expenses.planned)} />
              <Row label="Simplificada 5%" value={currency(est.simplificada)} />
            </Paper>
            <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                Seguridad Social (RETA)
              </Typography>
              <Row label="Monthly cuota" value={currency(est.ss.monthly_cuota)} />
              <Row label="Paid this year" value={currency(est.ss.paid)} />
              <Row label="Remaining" value={currency(est.ss.remaining)} />
              {est.ss.tarifa_plana && (
                <Chip size="small" label="Tarifa plana 80€" sx={{ mt: 1 }} />
              )}
            </Paper>
            <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                IRPF
              </Typography>
              <Row label="Modelo 130 this installment" value={currency(est.modelo_130.this_installment)} />
              <Row label="130 paid" value={currency(est.modelo_130.paid)} />
              <Row label="Withholdings" value={currency(est.modelo_130.withholdings)} />
              <Row label="130 remaining" value={currency(est.modelo_130.remaining)} />
              <Row label="Annual IRPF (estatal)" value={currency(est.irpf_annual.gross)} />
              <Row
                label="Renta remainder"
                value={currency(est.irpf_annual.renta_remainder)}
              />
            </Paper>
          </Stack>

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
                    <TableRow key={`${p.recurrence}-${p.date}-${i}`}>
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
                No tax recurrences scheduled. Mark cuota / modelo 130 payments as
                Recurring with category Tax to track them here.
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
                <MenuItem value="invoices">Issued invoices</MenuItem>
                <MenuItem value="tags">Bank income (all inflows)</MenuItem>
              </TextField>
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
                <MenuItem value="table">RETA tramos (minimum cuota)</MenuItem>
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
                helperText="Leave empty to use income recurrences + draft invoices"
              />
              <TagMultiSelect
                tags={tags}
                value={form.deductible_tags}
                onChange={(v) => setForm({ ...form, deductible_tags: v })}
                label="Deductible expense tags"
              />
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
