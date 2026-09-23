import { useEffect, useMemo, useState } from "react";
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
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import { useNavigate } from "react-router-dom";
import api from "../api";

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

const BLANK = {
  name: "",
  short_name: "",
  tax_id: "",
  address: "",
  vat_mode: "reverse_charge",
  default_vat_rate: "0",
  default_description: "",
  billing_unit: "hour",
  default_unit_price: "30",
  currency: "EUR",
  match_text: "",
  active_from: "",
  active_to: "",
  notes: "",
};

export default function Clients() {
  const navigate = useNavigate();
  const [clients, setClients] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(BLANK);

  const load = async () => {
    const { data } = await api.get("/clients/", { params: { page_size: 200 } });
    setClients(data.results);
  };

  useEffect(() => {
    load();
  }, []);

  const openNew = () => {
    setForm(BLANK);
    setOpen(true);
  };

  const save = async () => {
    const payload = {
      ...form,
      default_vat_rate: form.default_vat_rate || "0",
      default_unit_price: form.default_unit_price || "0",
      active_from: form.active_from || null,
      active_to: form.active_to || null,
    };
    const { data } = await api.post("/clients/", payload);
    setOpen(false);
    navigate(`/clients/${data.id}/details`);
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

  const columns = useMemo(
    () => [
      {
        field: "name",
        headerName: "Name",
        flex: 1,
        minWidth: 200,
        renderCell: (p) => (
          <Button
            size="small"
            onClick={() => navigate(`/clients/${p.row.id}/details`)}
            sx={{ textTransform: "none", fontWeight: 600, justifyContent: "flex-start" }}
          >
            {p.row.short_name ? `${p.row.short_name} · ${p.value}` : p.value}
          </Button>
        ),
      },
      {
        field: "is_active",
        headerName: "Status",
        width: 120,
        renderCell: (p) => (
          <Chip
            size="small"
            color={p.value ? "success" : "default"}
            label={p.value ? "Active" : "Inactive"}
          />
        ),
      },
      {
        field: "default_unit_price",
        headerName: "Rate",
        width: 140,
        valueGetter: (_, row) =>
          `${row.default_unit_price} ${row.currency}/${row.billing_unit === "day" ? "day" : "h"}`,
      },
      {
        field: "vat_mode",
        headerName: "VAT",
        width: 170,
        valueGetter: (value) => vatLabel(value),
      },
      { field: "tax_id", headerName: "Tax ID", width: 140 },
      { field: "active_from", headerName: "Start", width: 120 },
      {
        field: "active_to",
        headerName: "Termination",
        width: 130,
        valueGetter: (value) => value || "open",
      },
      { field: "match_text", headerName: "Bank match", width: 140 },
      {
        field: "actions",
        headerName: "",
        width: 70,
        sortable: false,
        filterable: false,
        renderCell: (p) => (
          <IconButton
            size="small"
            color="error"
            onClick={(e) => {
              e.stopPropagation();
              remove(p.row);
            }}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        ),
      },
    ],
    [navigate]
  );

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

      <DataGrid
        autoHeight
        rows={clients}
        columns={columns}
        pageSizeOptions={[25, 50, 100]}
        initialState={{
          pagination: { paginationModel: { pageSize: 25 } },
          sorting: { sortModel: [{ field: "is_active", sort: "desc" }] },
        }}
        disableRowSelectionOnClick
        onRowClick={(p) => navigate(`/clients/${p.id}/details`)}
        getRowClassName={(p) => (p.row.is_active ? "" : "row-inactive")}
        sx={{
          bgcolor: "background.paper",
          "& .MuiDataGrid-cell": {
            display: "flex",
            alignItems: "center",
          },
          "& .MuiDataGrid-row": { cursor: "pointer" },
          "& .row-inactive": { opacity: 0.6 },
        }}
      />
      {clients.length === 0 && (
        <Typography color="text.secondary" sx={{ mt: 2 }}>
          No clients yet.
        </Typography>
      )}

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>New client</DialogTitle>
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
              label="Default description"
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
              helperText="Attach salary inflows whose counterparty/concept contains this"
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
