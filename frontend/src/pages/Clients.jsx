import { useEffect, useState } from "react";
import {
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
import BusinessIcon from "@mui/icons-material/Business";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import api from "../api";

const VAT_MODES = [
  { value: "reverse_charge", label: "Reverse charge (NP)" },
  { value: "exempt", label: "Exempt (ZW)" },
  { value: "standard", label: "Standard VAT" },
];

const CURRENCIES = ["EUR", "USD", "GBP", "PLN", "CHF"];

const BLANK = {
  name: "",
  tax_id: "",
  address: "",
  vat_mode: "reverse_charge",
  default_vat_rate: "0",
  default_description: "",
  default_unit_price: "30",
  currency: "EUR",
  notes: "",
};

export default function Clients() {
  const [clients, setClients] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);

  const load = async () => {
    const { data } = await api.get("/clients/", { params: { page_size: 200 } });
    setClients(data.results);
  };

  useEffect(() => {
    load();
  }, []);

  const openNew = () => {
    setEditing(null);
    setForm(BLANK);
    setOpen(true);
  };

  const openEdit = (client) => {
    setEditing(client);
    setForm({
      name: client.name,
      tax_id: client.tax_id || "",
      address: client.address || "",
      vat_mode: client.vat_mode,
      default_vat_rate: String(client.default_vat_rate ?? "0"),
      default_description: client.default_description || "",
      default_unit_price: String(client.default_unit_price ?? "0"),
      currency: client.currency || "EUR",
      notes: client.notes || "",
    });
    setOpen(true);
  };

  const save = async () => {
    const payload = {
      ...form,
      default_vat_rate: form.default_vat_rate || "0",
      default_unit_price: form.default_unit_price || "0",
    };
    if (editing) await api.patch(`/clients/${editing.id}/`, payload);
    else await api.post("/clients/", payload);
    setOpen(false);
    load();
  };

  const remove = async (client) => {
    if (!window.confirm(`Delete client "${client.name}"?`)) return;
    try {
      await api.delete(`/clients/${client.id}/`);
      load();
    } catch (e) {
      window.alert(e.response?.data?.detail || "Could not delete client (invoices may reference it).");
    }
  };

  const vatLabel = (mode) => VAT_MODES.find((m) => m.value === mode)?.label || mode;

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Clients
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          New client
        </Button>
      </Stack>

      <Stack spacing={1}>
        {clients.map((c) => (
          <Paper
            key={c.id}
            variant="outlined"
            sx={{ p: 1.5, display: "flex", alignItems: "center", gap: 2 }}
          >
            <BusinessIcon color="action" />
            <Box sx={{ flexGrow: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Typography sx={{ fontWeight: 600 }}>{c.name}</Typography>
                <Chip size="small" variant="outlined" label={vatLabel(c.vat_mode)} />
                <Chip size="small" variant="outlined" label={c.currency} />
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {[c.tax_id && `NIP/VAT ${c.tax_id}`, c.default_description].filter(Boolean).join(" · ") ||
                  "—"}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Default {c.default_unit_price} {c.currency}/h
                {c.address ? ` · ${c.address}` : ""}
              </Typography>
            </Box>
            <IconButton size="small" onClick={() => openEdit(c)}>
              <EditIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" color="error" onClick={() => remove(c)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Paper>
        ))}
        {clients.length === 0 && (
          <Typography color="text.secondary">No clients yet.</Typography>
        )}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{editing ? "Edit client" : "New client"}</DialogTitle>
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
              label="Tax ID / NIP"
              value={form.tax_id}
              onChange={(e) => setForm({ ...form, tax_id: e.target.value })}
              fullWidth
            />
            <TextField
              label="Address"
              value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })}
              fullWidth
              multiline
              minRows={2}
            />
            <TextField
              select
              label="VAT mode"
              value={form.vat_mode}
              onChange={(e) => setForm({ ...form, vat_mode: e.target.value })}
              fullWidth
            >
              {VAT_MODES.map((m) => (
                <MenuItem key={m.value} value={m.value}>
                  {m.label}
                </MenuItem>
              ))}
            </TextField>
            {form.vat_mode === "standard" && (
              <TextField
                label="VAT rate %"
                type="number"
                value={form.default_vat_rate}
                onChange={(e) => setForm({ ...form, default_vat_rate: e.target.value })}
                fullWidth
              />
            )}
            <TextField
              label="Default description"
              value={form.default_description}
              onChange={(e) => setForm({ ...form, default_description: e.target.value })}
              fullWidth
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                label="Default unit price"
                type="number"
                value={form.default_unit_price}
                onChange={(e) => setForm({ ...form, default_unit_price: e.target.value })}
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
            </Stack>
            <TextField
              label="Notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              fullWidth
              multiline
              minRows={2}
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
