import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import DownloadIcon from "@mui/icons-material/Download";
import EditIcon from "@mui/icons-material/Edit";
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";
import LockIcon from "@mui/icons-material/Lock";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { Link as RouterLink, useOutletContext, useParams } from "react-router-dom";
import api from "../api";
import { money } from "../money";

const MONTHS = [
  [1, "January"],
  [2, "February"],
  [3, "March"],
  [4, "April"],
  [5, "May"],
  [6, "June"],
  [7, "July"],
  [8, "August"],
  [9, "September"],
  [10, "October"],
  [11, "November"],
  [12, "December"],
];

const blankInvoice = () => {
  const now = new Date();
  const service = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return {
    client: "",
    account: "",
    service_year: service.getFullYear(),
    service_month: service.getMonth() + 1,
    issue_date: now.toISOString().slice(0, 10),
    sale_date: "",
    due_date: "",
    description: "",
    quantity: "",
    unit: "hour",
    unit_price: "",
    currency: "EUR",
    number: "",
    notes: "",
  };
};

export default function Invoices() {
  const { clientId } = useParams();
  const { client: routeClient } = useOutletContext();
  const lockedClientId = clientId ? Number(clientId) : null;

  const [invoices, setInvoices] = useState([]);
  const [clients, setClients] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [issuer, setIssuer] = useState(null);
  const [error, setError] = useState("");

  const [invOpen, setInvOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(blankInvoice());
  const [advice, setAdvice] = useState(null);

  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState(null);

  const load = async () => {
    const [inv, cli, acc, iss] = await Promise.all([
      api.get("/invoices/", {
        params: { page_size: 200, ...(lockedClientId ? { client: lockedClientId } : {}) },
      }),
      api.get("/clients/", { params: { page_size: 200 } }),
      api.get("/accounts/", { params: { page_size: 200 } }),
      api.get("/issuer/"),
    ]);
    setInvoices(inv.data.results);
    setClients(cli.data.results);
    setAccounts(acc.data.results);
    setIssuer(iss.data);
  };

  useEffect(() => {
    load().catch((e) => setError(e.response?.data?.detail || e.message));
  }, [lockedClientId]);

  const invoiceAccounts = useMemo(
    () => accounts.filter((a) => (a.kind || "bank") === "bank" && (a.iban || a.is_invoice_default)),
    [accounts]
  );

  const lockedClient =
    routeClient || clients.find((c) => c.id === lockedClientId) || null;

  const refreshAdvice = async (year, month, unitPrice, unit = "hour", clientId) => {
    const { data } = await api.get("/invoices/advise/", {
      params: {
        year,
        month,
        unit_price: unitPrice || undefined,
        unit,
        client: clientId || undefined,
      },
    });
    setAdvice(data);
    return data;
  };

  const openNewInvoice = async () => {
    setEditing(null);
    const base = blankInvoice();
    const defaultClient = routeClient || clients.find((c) => c.id === lockedClientId) || clients[0];
    const defaultAccount =
      accounts.find((a) => a.is_invoice_default) || accounts.find((a) => a.iban) || "";
    if (defaultClient) {
      base.client = defaultClient.id;
      base.description = defaultClient.default_description || "";
      base.unit_price = defaultClient.default_unit_price || "30";
      base.currency = defaultClient.currency || "EUR";
      base.unit = defaultClient.billing_unit || "hour";
    }
    if (defaultAccount) base.account = defaultAccount.id || defaultAccount;
    const adv = await refreshAdvice(
      base.service_year,
      base.service_month,
      base.unit_price,
      base.unit,
      defaultClient?.id
    );
    base.quantity = String(adv.suggested_quantity ?? adv.suggested_hours);
    base.sale_date = adv.sale_date;
    base.due_date = adv.suggested_due_date;
    base.number = adv.suggested_number;
    setForm(base);
    setInvOpen(true);
  };

  const openEditInvoice = (inv) => {
    if (inv.is_issued) return;
    setEditing(inv);
    setForm({
      client: inv.client,
      account: inv.account || "",
      service_year: inv.service_year,
      service_month: inv.service_month,
      issue_date: inv.issue_date,
      sale_date: inv.sale_date,
      due_date: inv.due_date,
      description: inv.description,
      quantity: String(inv.quantity),
      unit: inv.unit || "hour",
      unit_price: String(inv.unit_price),
      currency: inv.currency,
      number: inv.number,
      notes: inv.notes || "",
    });
    refreshAdvice(
      inv.service_year,
      inv.service_month,
      inv.unit_price,
      inv.unit || "hour",
      inv.client
    );
    setInvOpen(true);
  };

  const onServiceChange = async (year, month) => {
    const next = { ...form, service_year: year, service_month: month };
    const adv = await refreshAdvice(year, month, next.unit_price, next.unit, next.client);
    next.quantity = String(adv.suggested_quantity ?? adv.suggested_hours);
    next.sale_date = adv.sale_date;
    setForm(next);
  };

  const saveInvoice = async () => {
    setError("");
    const payload = {
      ...form,
      client: form.client || lockedClientId,
      account: form.account || null,
      quantity: form.quantity,
      unit_price: form.unit_price,
    };
    try {
      if (editing) await api.patch(`/invoices/${editing.id}/`, payload);
      else await api.post("/invoices/", payload);
      setInvOpen(false);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || JSON.stringify(e.response?.data) || e.message);
    }
  };

  const issueInvoice = async (inv) => {
    if (!window.confirm(`Issue invoice #${inv.number}? It becomes immutable.`)) return;
    try {
      await api.post(`/invoices/${inv.id}/issue/`);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  const removeInvoice = async (inv) => {
    if (!window.confirm(`Delete draft #${inv.number}?`)) return;
    try {
      await api.delete(`/invoices/${inv.id}/`);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  const download = async (inv, kind, redacted = false) => {
    const res = await api.get(`/invoices/${inv.id}/download/`, {
      params: { kind, ...(redacted ? { redacted: 1 } : {}) },
      responseType: "blob",
    });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `invoice-${inv.number}${redacted ? "-redacted" : ""}.${kind}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const runImport = async () => {
    if (!importFile || !lockedClientId) return;
    const body = new FormData();
    body.append("file", importFile);
    body.append("client", lockedClientId);
    try {
      await api.post("/invoices/import_xlsx/", body);
      setImportOpen(false);
      setImportFile(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  const previewNet =
    form.quantity && form.unit_price
      ? Number(form.quantity) * Number(form.unit_price)
      : null;

  return (
    <Box>
      <Stack direction="row" justifyContent="flex-end" alignItems="center" sx={{ mb: 2 }}>
        <Stack direction="row" spacing={1}>
          <Button startIcon={<UploadFileIcon />} onClick={() => setImportOpen(true)}>
            Import XLSX
          </Button>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={openNewInvoice}
            disabled={clients.length === 0 && !routeClient}
          >
            New invoice
          </Button>
        </Stack>
      </Stack>

      {!issuer && (
        <Alert
          severity="warning"
          sx={{ mb: 2 }}
          action={
            <Button component={RouterLink} to="/my/details" color="inherit">
              My → Details
            </Button>
          }
        >
          Issuer profile is required before issuing invoices. Set it under My → Details.
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {typeof error === "string" ? error : JSON.stringify(error)}
        </Alert>
      )}
      {clients.length === 0 && !routeClient && (
        <Alert
          severity="info"
          sx={{ mb: 2 }}
          action={
            <Button component={RouterLink} to="/clients" color="inherit">
              Add client
            </Button>
          }
        >
          Add a client before creating invoices.
        </Alert>
      )}

      <Stack spacing={1}>
        {invoices.map((inv) => (
          <Paper
            key={inv.id}
            variant="outlined"
            sx={{ p: 1.5, display: "flex", alignItems: "center", gap: 2 }}
          >
            <Box sx={{ flexGrow: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Typography sx={{ fontWeight: 700 }}>#{inv.number}</Typography>
                <Chip
                  size="small"
                  color={inv.is_issued ? "success" : "default"}
                  icon={inv.is_issued ? <LockIcon /> : undefined}
                  label={inv.status}
                />
                {!lockedClientId && (
                  <Chip size="small" variant="outlined" label={inv.client_label || inv.client_name} />
                )}
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {inv.description} · {inv.quantity}
                {inv.unit === "day" ? "d" : "h"} × {inv.unit_price} · sale {inv.sale_date} ·
                issue {inv.issue_date}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Bank snapshot: {inv.iban || "—"}
                {inv.account_name ? ` (${inv.account_name})` : ""}
              </Typography>
            </Box>
            <Typography sx={{ fontWeight: 600, whiteSpace: "nowrap" }}>
              {money(inv.total_amount, inv.currency)}
            </Typography>
            <Button size="small" onClick={() => download(inv, "pdf")} startIcon={<DownloadIcon />}>
              PDF
            </Button>
            <Button
              size="small"
              onClick={() => download(inv, "pdf", true)}
              startIcon={<VisibilityOffIcon />}
            >
              Redacted
            </Button>
            <Button size="small" onClick={() => download(inv, "xlsx")}>
              XLSX
            </Button>
            <Button size="small" onClick={() => download(inv, "xlsx", true)}>
              XLSX redacted
            </Button>
            {!inv.is_issued && (
              <>
                <Button size="small" variant="contained" onClick={() => issueInvoice(inv)}>
                  Issue
                </Button>
                <IconButton size="small" onClick={() => openEditInvoice(inv)}>
                  <EditIcon fontSize="small" />
                </IconButton>
                <IconButton size="small" color="error" onClick={() => removeInvoice(inv)}>
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </>
            )}
          </Paper>
        ))}
        {invoices.length === 0 && (
          <Typography color="text.secondary">No invoices yet.</Typography>
        )}
      </Stack>

      <Dialog open={invOpen} onClose={() => setInvOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>{editing ? `Edit draft #${editing.number}` : "New invoice"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {advice && (
              <Alert severity="info">
                Working days in {advice.month}/{advice.year}: <b>{advice.working_days}</b> →
                suggested{" "}
                <b>
                  {advice.suggested_quantity ?? advice.suggested_hours}
                  {form.unit === "day" ? " days" : "h"}
                </b>
                {advice.suggested_net != null && <> · advisory net {money(advice.suggested_net, form.currency)}</>}
                {form.unit === "day"
                  ? " (Mon–Fri days; override below)"
                  : " (8 × Mon–Fri; override hours below)"}
              </Alert>
            )}
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              {!lockedClientId && (
                <TextField
                  select
                  label="Client"
                  value={form.client}
                  onChange={(e) => {
                    const c = clients.find((x) => x.id === Number(e.target.value));
                    const unit = c?.billing_unit || form.unit;
                    setForm({
                      ...form,
                      client: e.target.value,
                      description: c?.default_description || form.description,
                      unit_price: c?.default_unit_price || form.unit_price,
                      currency: c?.currency || form.currency,
                      unit,
                    });
                    refreshAdvice(
                      form.service_year,
                      form.service_month,
                      c?.default_unit_price || form.unit_price,
                      unit,
                      c?.id
                    );
                  }}
                  fullWidth
                >
                  {clients.map((c) => (
                    <MenuItem key={c.id} value={c.id}>
                      {c.name}
                    </MenuItem>
                  ))}
                </TextField>
              )}
              <TextField
                select
                label="Bank account"
                value={form.account}
                onChange={(e) => setForm({ ...form, account: e.target.value })}
                fullWidth
                helperText="Requisites snapshotted when issued"
              >
                {(invoiceAccounts.length ? invoiceAccounts : accounts).map((a) => (
                  <MenuItem key={a.id} value={a.id}>
                    {a.name} {a.iban ? `· ${a.iban}` : ""}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                select
                label="Service month"
                value={form.service_month}
                onChange={(e) => onServiceChange(form.service_year, Number(e.target.value))}
                fullWidth
              >
                {MONTHS.map(([m, label]) => (
                  <MenuItem key={m} value={m}>
                    {label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="Service year"
                type="number"
                value={form.service_year}
                onChange={(e) => onServiceChange(Number(e.target.value), form.service_month)}
                fullWidth
              />
              <TextField
                label="Invoice #"
                value={form.number}
                onChange={(e) => setForm({ ...form, number: e.target.value })}
                fullWidth
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                label="Sale date"
                type="date"
                InputLabelProps={{ shrink: true }}
                value={form.sale_date}
                onChange={(e) => setForm({ ...form, sale_date: e.target.value })}
                fullWidth
              />
              <TextField
                label="Issue date"
                type="date"
                InputLabelProps={{ shrink: true }}
                value={form.issue_date}
                onChange={(e) => setForm({ ...form, issue_date: e.target.value })}
                fullWidth
              />
              <TextField
                label="Due date"
                type="date"
                InputLabelProps={{ shrink: true }}
                value={form.due_date}
                onChange={(e) => setForm({ ...form, due_date: e.target.value })}
                fullWidth
              />
            </Stack>
            <TextField
              label="Description"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              fullWidth
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                label={form.unit === "day" ? "Days" : "Hours"}
                type="number"
                value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                fullWidth
              />
              <TextField
                label="Unit price"
                type="number"
                value={form.unit_price}
                onChange={(e) => setForm({ ...form, unit_price: e.target.value })}
                fullWidth
              />
              <TextField
                label="Currency"
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                fullWidth
              />
            </Stack>
            {previewNet != null && (
              <Typography>
                Net: <b>{money(previewNet, form.currency)}</b>
              </Typography>
            )}
            <TextField
              label="Notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              fullWidth
              multiline
              minRows={3}
              helperText="Reverse-charge note is filled automatically for NP clients if left empty"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setInvOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={saveInvoice}
            disabled={!(form.client || lockedClientId) || !form.quantity || !form.unit_price}
          >
            Save draft
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={importOpen} onClose={() => setImportOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Import existing invoice (XLSX)</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              Client: {lockedClient?.name || "—"}
            </Typography>
            <Button variant="outlined" component="label">
              {importFile ? importFile.name : "Choose .xlsx"}
              <input
                hidden
                type="file"
                accept=".xlsx"
                onChange={(e) => setImportFile(e.target.files?.[0] || null)}
              />
            </Button>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setImportOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={runImport}
            disabled={!importFile || !lockedClientId}
          >
            Import as issued
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
