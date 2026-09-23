import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useOutletContext } from "react-router-dom";
import api from "../../api";

const VAT_MODES = [
  { value: "reverse_charge", label: "Reverse charge (NP)" },
  { value: "exempt", label: "Exempt (ZW)" },
  { value: "standard", label: "Standard VAT" },
];

const CURRENCIES = ["EUR", "USD", "GBP", "PLN", "CHF"];
const BILLING_UNITS = [
  { value: "hour", label: "Hour" },
  { value: "day", label: "Day" },
];

function fromClient(client) {
  return {
    name: client.name || "",
    short_name: client.short_name || "",
    tax_id: client.tax_id || "",
    address: client.address || "",
    vat_mode: client.vat_mode || "reverse_charge",
    default_vat_rate: String(client.default_vat_rate ?? "0"),
    default_description: client.default_description || "",
    billing_unit: client.billing_unit || "hour",
    default_unit_price: String(client.default_unit_price ?? "0"),
    currency: client.currency || "EUR",
    match_text: client.match_text || "",
    active_from: client.active_from || "",
    active_to: client.active_to || "",
    notes: client.notes || "",
  };
}

export default function ClientDetails() {
  const { client, setClient } = useOutletContext();
  const [form, setForm] = useState(() => fromClient(client));
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setForm(fromClient(client));
  }, [client]);

  const save = async () => {
    setError("");
    setSaved(false);
    try {
      const { data } = await api.patch(`/clients/${client.id}/`, {
        ...form,
        default_vat_rate: form.default_vat_rate || "0",
        default_unit_price: form.default_unit_price || "0",
        active_from: form.active_from || null,
        active_to: form.active_to || null,
      });
      setClient(data);
      setSaved(true);
    } catch (e) {
      setError(e.response?.data?.detail || JSON.stringify(e.response?.data) || e.message);
    }
  };

  return (
    <Box maxWidth={560}>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Client details are copied onto invoices at issue time.
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}
      {saved && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
          Saved.
        </Alert>
      )}
      <Stack spacing={2}>
        <TextField
          label="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          fullWidth
          required
        />
        <TextField
          label="Short name"
          value={form.short_name}
          onChange={(e) => setForm({ ...form, short_name: e.target.value })}
          helperText="Shown on the tax forecast columns"
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
          label="Default invoice description"
          value={form.default_description}
          onChange={(e) => setForm({ ...form, default_description: e.target.value })}
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Billed by"
            value={form.billing_unit}
            onChange={(e) => setForm({ ...form, billing_unit: e.target.value })}
            fullWidth
          >
            {BILLING_UNITS.map((u) => (
              <MenuItem key={u.value} value={u.value}>
                {u.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label={form.billing_unit === "day" ? "Daily rate" : "Hourly rate"}
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
          label="Bank match text"
          value={form.match_text}
          onChange={(e) => setForm({ ...form, match_text: e.target.value })}
          helperText="Salary inflows whose counterparty/concept contains this are attached to this client"
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Contract start"
            type="date"
            value={form.active_from}
            onChange={(e) => setForm({ ...form, active_from: e.target.value })}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
          <TextField
            label="Termination date"
            type="date"
            value={form.active_to}
            onChange={(e) => setForm({ ...form, active_to: e.target.value })}
            InputLabelProps={{ shrink: true }}
            helperText="Leave empty if the engagement is still open"
            fullWidth
          />
        </Stack>
        <TextField
          label="Notes"
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
          fullWidth
          multiline
          minRows={2}
        />
        <Box>
          <Button
            variant="contained"
            onClick={save}
            disabled={!form.name.trim()}
          >
            Save details
          </Button>
        </Box>
      </Stack>
    </Box>
  );
}
