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
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import api from "../api";

const BLANK = { name: "", bank: "", iban: "", currency: "EUR", is_default: false };

const CURRENCIES = ["EUR", "USD", "GBP", "PLN", "CHF"];

export default function Accounts() {
  const [accounts, setAccounts] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);

  const load = async () => {
    const { data } = await api.get("/accounts/", { params: { page_size: 200 } });
    setAccounts(data.results);
  };

  useEffect(() => {
    load();
  }, []);

  const openNew = () => {
    setEditing(null);
    setForm({ ...BLANK, is_default: accounts.length === 0 });
    setOpen(true);
  };

  const openEdit = (account) => {
    setEditing(account);
    setForm({
      name: account.name,
      bank: account.bank || "",
      iban: account.iban || "",
      currency: account.currency || "EUR",
      is_default: account.is_default,
    });
    setOpen(true);
  };

  const save = async () => {
    if (editing) await api.patch(`/accounts/${editing.id}/`, form);
    else await api.post("/accounts/", form);
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

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Accounts
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          New account
        </Button>
      </Stack>

      <Stack spacing={1}>
        {accounts.map((a) => (
          <Paper
            key={a.id}
            variant="outlined"
            sx={{ p: 1.5, display: "flex", alignItems: "center", gap: 2 }}
          >
            <AccountBalanceIcon color="action" />
            <Box sx={{ flexGrow: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center">
                <Typography sx={{ fontWeight: 600 }}>{a.name}</Typography>
                {a.is_default && <Chip size="small" color="primary" label="Default" />}
                <Chip size="small" variant="outlined" label={a.currency} />
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {[a.bank, a.iban].filter(Boolean).join(" · ") || "—"}
              </Typography>
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
        {accounts.length === 0 && (
          <Typography color="text.secondary">No accounts yet.</Typography>
        )}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>{editing ? "Edit account" : "New account"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              autoFocus
              fullWidth
            />
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
            <TextField
              select
              label="Currency"
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
              fullWidth
            >
              {CURRENCIES.map((c) => (
                <MenuItem key={c} value={c}>
                  {c}
                </MenuItem>
              ))}
            </TextField>
            <FormControlLabel
              control={
                <Switch
                  checked={form.is_default}
                  onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                />
              }
              label="Default account for uploads"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={save} disabled={!form.name.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
