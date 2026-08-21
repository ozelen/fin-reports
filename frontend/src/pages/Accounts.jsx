import { useEffect, useState } from "react";
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
import AccountBalanceIcon from "@mui/icons-material/AccountBalance";
import AccountBalanceWalletIcon from "@mui/icons-material/AccountBalanceWallet";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import PeopleAltIcon from "@mui/icons-material/PeopleAlt";
import SwapHorizIcon from "@mui/icons-material/SwapHoriz";
import api from "../api";

const BLANK = {
  name: "",
  kind: "bank",
  bank: "",
  iban: "",
  bic: "",
  correspondent_bic: "",
  bank_address: "",
  currency: "EUR",
  balance: "0",
  credit_limit: "",
  is_credit: false,
  group: "family",
  is_default: false,
  is_invoice_default: false,
};

const CURRENCIES = ["EUR", "USD", "GBP", "PLN", "CHF", "UAH"];
const GROUPS = [
  { value: "family", label: "Family" },
  { value: "personal", label: "Personal" },
];
const KINDS = [
  { value: "bank", label: "Bank accounts" },
  { value: "cash", label: "Cash wallets" },
  { value: "debt", label: "Debts" },
];
const KIND_LABELS = {
  bank: "Bank",
  cash: "Cash wallet",
  debt: "Debt",
};

const todayIso = () => new Date().toISOString().slice(0, 10);

const money = (v, code) =>
  new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: code || "EUR",
  }).format(v || 0);

function KindIcon({ kind }) {
  if (kind === "cash") return <AccountBalanceWalletIcon color="action" />;
  if (kind === "debt") return <PeopleAltIcon color="action" />;
  return <AccountBalanceIcon color="action" />;
}

export default function Accounts() {
  const [accounts, setAccounts] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [xferOpen, setXferOpen] = useState(false);
  const [xfer, setXfer] = useState({
    from_account: "",
    to_account: "",
    amount: "",
    operation_date: todayIso(),
    concept: "",
  });
  const [xferError, setXferError] = useState("");

  const load = async () => {
    const { data } = await api.get("/accounts/", { params: { page_size: 200 } });
    setAccounts(data.results);
  };

  useEffect(() => {
    load();
  }, []);

  const openNew = () => {
    setEditing(null);
    setForm({ ...BLANK, is_default: accounts.filter((a) => a.kind === "bank").length === 0 });
    setOpen(true);
  };

  const openEdit = (account) => {
    setEditing(account);
    setForm({
      name: account.name,
      kind: account.kind || "bank",
      bank: account.bank || "",
      iban: account.iban || "",
      bic: account.bic || "",
      correspondent_bic: account.correspondent_bic || "",
      bank_address: account.bank_address || "",
      currency: account.currency || "EUR",
      balance: account.balance ?? "0",
      credit_limit: account.credit_limit ?? "",
      is_credit: Boolean(account.credit_limit),
      group: account.group || "family",
      is_default: account.is_default,
      is_invoice_default: account.is_invoice_default,
    });
    setOpen(true);
  };

  const payload = () => {
    const { is_credit, ...fields } = form;
    return {
      ...fields,
      balance: form.balance === "" ? "0" : form.balance,
      credit_limit: is_credit && form.credit_limit !== "" ? form.credit_limit : null,
      is_default: form.kind === "bank" && form.is_default,
      is_invoice_default: form.kind === "bank" && form.is_invoice_default,
    };
  };

  const save = async () => {
    if (editing) await api.patch(`/accounts/${editing.id}/`, payload());
    else await api.post("/accounts/", payload());
    setOpen(false);
    load();
  };

  const remove = async (account) => {
    const msg = account.transaction_count
      ? `Delete "${account.name}"? Its ${account.transaction_count} transaction(s) will remain but become unassigned.`
      : `Delete "${account.name}"?`;
    if (!window.confirm(msg)) return;
    await api.delete(`/accounts/${account.id}/`);
    load();
  };

  const openTransfer = () => {
    setXfer({
      from_account: accounts[0]?.id || "",
      to_account: accounts[1]?.id || "",
      amount: "",
      operation_date: todayIso(),
      concept: "",
    });
    setXferError("");
    setXferOpen(true);
  };

  const saveTransfer = async () => {
    setXferError("");
    try {
      await api.post("/accounts/transfer/", {
        from_account: xfer.from_account,
        to_account: xfer.to_account,
        amount: xfer.amount,
        operation_date: xfer.operation_date,
        concept: xfer.concept,
      });
      setXferOpen(false);
      load();
    } catch (err) {
      const data = err.response?.data;
      const detail =
        (typeof data === "string" && data) ||
        data?.detail ||
        (data && Object.values(data).flat().join(" ")) ||
        "Transfer failed.";
      setXferError(detail);
    }
  };

  const isBank = form.kind === "bank";

  return (
    <Box>
      <Stack direction="row" justifyContent="flex-end" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <Button
          variant="outlined"
          startIcon={<SwapHorizIcon />}
          onClick={openTransfer}
          disabled={accounts.length < 2}
        >
          Transfer
        </Button>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          New account
        </Button>
      </Stack>

      <Stack spacing={3}>
        {KINDS.map((kind) => {
          const items = accounts.filter((a) => (a.kind || "bank") === kind.value);
          if (accounts.length > 0 && items.length === 0) return null;
          if (accounts.length === 0) return null;
          return (
            <Box key={kind.value}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                {kind.label}
              </Typography>
              {kind.value === "debt" && (
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                  Positive: they owe you. Negative: you owe them.
                </Typography>
              )}
              <Stack spacing={2}>
                {GROUPS.map((g) => {
                  const groupItems = items.filter((a) => a.group === g.value);
                  if (items.length > 0 && groupItems.length === 0) return null;
                  return (
                    <Box key={g.value}>
                      <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                        {g.label}
                      </Typography>
                      <Stack spacing={1}>
                        {groupItems.map((a) => (
                          <Paper
                            key={a.id}
                            variant="outlined"
                            sx={{ p: 1.5, display: "flex", alignItems: "center", gap: 2 }}
                          >
                            <KindIcon kind={a.kind} />
                            <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                                <Typography sx={{ fontWeight: 600 }}>{a.name}</Typography>
                                {a.is_default && (
                                  <Chip size="small" color="primary" label="Upload default" />
                                )}
                                {a.is_invoice_default && (
                                  <Chip size="small" color="secondary" label="Invoice default" />
                                )}
                                {a.credit_limit && (
                                  <Chip size="small" variant="outlined" label="Credit card" />
                                )}
                                <Chip size="small" variant="outlined" label={a.currency} />
                              </Stack>
                              <Typography variant="body2" color="text.secondary">
                                {a.kind === "bank"
                                  ? [a.bank, a.iban, a.bic && `BIC ${a.bic}`].filter(Boolean).join(" · ") ||
                                    "—"
                                  : KIND_LABELS[a.kind] || a.kind}
                              </Typography>
                            </Box>
                            <Box sx={{ minWidth: 140, textAlign: "right" }}>
                              <Typography
                                sx={{
                                  fontWeight: 700,
                                  color:
                                    Number(a.effective_balance ?? a.balance) < 0
                                      ? "error.main"
                                      : Number(a.effective_balance ?? a.balance) > 0
                                        ? "success.main"
                                        : "text.secondary",
                                }}
                              >
                                {money(a.effective_balance ?? a.balance, a.currency)}
                              </Typography>
                              {a.credit_limit && (
                                <Typography variant="caption" color="text.secondary">
                                  available {money(a.balance, a.currency)} of{" "}
                                  {money(a.credit_limit, a.currency)}
                                </Typography>
                              )}
                            </Box>
                            <Chip size="small" variant="outlined" label={`${a.transaction_count} tx`} />
                            <IconButton size="small" onClick={() => openEdit(a)}>
                              <EditIcon fontSize="small" />
                            </IconButton>
                            <IconButton size="small" color="error" onClick={() => remove(a)}>
                              <DeleteIcon fontSize="small" />
                            </IconButton>
                          </Paper>
                        ))}
                      </Stack>
                    </Box>
                  );
                })}
              </Stack>
            </Box>
          );
        })}
        {accounts.length === 0 && (
          <Typography color="text.secondary">No accounts yet.</Typography>
        )}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{editing ? "Edit account" : `New ${KIND_LABELS[form.kind] || "account"}`}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              select
              label="Type"
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}
              fullWidth
            >
              {KINDS.map((k) => (
                <MenuItem key={k.value} value={k.value}>
                  {KIND_LABELS[k.value]}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              autoFocus
              fullWidth
            />
            {isBank && (
              <>
                <TextField
                  label="Bank"
                  value={form.bank}
                  onChange={(e) => setForm({ ...form, bank: e.target.value })}
                  fullWidth
                />
                <TextField
                  label="IBAN"
                  value={form.iban}
                  onChange={(e) => setForm({ ...form, iban: e.target.value })}
                  fullWidth
                />
                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <TextField
                    label="BIC"
                    value={form.bic}
                    onChange={(e) => setForm({ ...form, bic: e.target.value })}
                    fullWidth
                  />
                  <TextField
                    label="Correspondent BIC"
                    value={form.correspondent_bic}
                    onChange={(e) => setForm({ ...form, correspondent_bic: e.target.value })}
                    fullWidth
                  />
                </Stack>
                <TextField
                  label="Bank address"
                  value={form.bank_address}
                  onChange={(e) => setForm({ ...form, bank_address: e.target.value })}
                  fullWidth
                  multiline
                  minRows={2}
                />
              </>
            )}
            <TextField
              select
              label="Group"
              value={form.group}
              onChange={(e) => setForm({ ...form, group: e.target.value })}
              fullWidth
            >
              {GROUPS.map((g) => (
                <MenuItem key={g.value} value={g.value}>
                  {g.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Currency"
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
              fullWidth
            >
              {CURRENCIES.map((c) => (
                <MenuItem key={c.value || c} value={c.value || c}>
                  {c}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Balance"
              type="number"
              value={form.balance}
              onChange={(e) => setForm({ ...form, balance: e.target.value })}
              fullWidth
              helperText={
                form.kind === "debt"
                  ? "Positive: they owe you. Negative: you owe them."
                  : form.is_credit
                    ? "Available credit from the last statement. Real balance = available − limit."
                    : form.kind === "bank"
                      ? "Filled from the last statement row. You can override."
                      : ""
              }
            />
            <FormControlLabel
              control={
                <Switch
                  checked={form.is_credit}
                  onChange={(e) =>
                    setForm({ ...form, is_credit: e.target.checked })
                  }
                />
              }
              label="Credit card (statement shows available credit)"
            />
            {form.is_credit && (
              <TextField
                label="Credit limit"
                type="number"
                value={form.credit_limit}
                onChange={(e) => setForm({ ...form, credit_limit: e.target.value })}
                fullWidth
                helperText="Real balance = available credit − this limit (shown as negative when you owe)."
              />
            )}
            {isBank && (
              <>
                <FormControlLabel
                  control={
                    <Switch
                      checked={form.is_default}
                      onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                    />
                  }
                  label="Default account for uploads"
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={form.is_invoice_default}
                      onChange={(e) =>
                        setForm({ ...form, is_invoice_default: e.target.checked })
                      }
                    />
                  }
                  label="Default account for invoices (requisites are snapshotted on issue)"
                />
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={save} disabled={!form.name.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={xferOpen} onClose={() => setXferOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Transfer</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              select
              label="From"
              value={xfer.from_account}
              onChange={(e) => setXfer({ ...xfer, from_account: e.target.value })}
              fullWidth
            >
              {accounts.map((a) => (
                <MenuItem key={a.id} value={a.id}>
                  {a.name} ({money(a.effective_balance ?? a.balance, a.currency)})
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="To"
              value={xfer.to_account}
              onChange={(e) => setXfer({ ...xfer, to_account: e.target.value })}
              fullWidth
            >
              {accounts.map((a) => (
                <MenuItem key={a.id} value={a.id}>
                  {a.name} ({money(a.effective_balance ?? a.balance, a.currency)})
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Amount"
              type="number"
              value={xfer.amount}
              onChange={(e) => setXfer({ ...xfer, amount: e.target.value })}
              fullWidth
            />
            <TextField
              label="Date"
              type="date"
              value={xfer.operation_date}
              onChange={(e) => setXfer({ ...xfer, operation_date: e.target.value })}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="Concept"
              value={xfer.concept}
              onChange={(e) => setXfer({ ...xfer, concept: e.target.value })}
              fullWidth
            />
            {xferError && (
              <Typography variant="body2" color="error">
                {xferError}
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setXferOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={saveTransfer}
            disabled={!xfer.from_account || !xfer.to_account || !xfer.amount}
          >
            Transfer
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
