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
import DescriptionIcon from "@mui/icons-material/Description";
import DownloadIcon from "@mui/icons-material/Download";
import EditIcon from "@mui/icons-material/Edit";
import api from "../api";

const KINDS = [
  { value: "agreement", label: "Agreement" },
  { value: "order", label: "Order" },
  { value: "offer", label: "Offer" },
  { value: "tax_declaration", label: "Tax declaration" },
  { value: "tax_certificate", label: "Tax certificate" },
  { value: "other", label: "Other" },
];

const SCOPES = [
  { value: "", label: "All" },
  { value: "personal", label: "Personal" },
  { value: "client", label: "Per client" },
];

const BLANK = {
  client: "",
  kind: "other",
  title: "",
  document_date: "",
  notes: "",
};

export default function Documents() {
  const [docs, setDocs] = useState([]);
  const [clients, setClients] = useState([]);
  const [scope, setScope] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [error, setError] = useState("");

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [file, setFile] = useState(null);

  const load = async () => {
    const params = { page_size: 200 };
    if (scope) params.scope = scope;
    if (kindFilter) params.kind = kindFilter;
    if (clientFilter) params.client = clientFilter;
    const [d, c] = await Promise.all([
      api.get("/documents/", { params }),
      api.get("/clients/", { params: { page_size: 200 } }),
    ]);
    setDocs(d.data.results);
    setClients(c.data.results);
  };

  useEffect(() => {
    load().catch((e) => setError(e.response?.data?.detail || e.message));
  }, [scope, kindFilter, clientFilter]);

  const openNew = () => {
    setEditing(null);
    setForm({
      ...BLANK,
      kind: scope === "personal" ? "tax_declaration" : "agreement",
      client: clientFilter || "",
    });
    setFile(null);
    setOpen(true);
  };

  const openEdit = (doc) => {
    setEditing(doc);
    setForm({
      client: doc.client || "",
      kind: doc.kind,
      title: doc.title,
      document_date: doc.document_date || "",
      notes: doc.notes || "",
    });
    setFile(null);
    setOpen(true);
  };

  const save = async () => {
    setError("");
    const body = new FormData();
    body.append("kind", form.kind);
    body.append("title", form.title.trim());
    body.append("notes", form.notes || "");
    if (form.document_date) body.append("document_date", form.document_date);
    if (form.client) body.append("client", form.client);
    else body.append("client", "");
    if (file) body.append("file", file);

    try {
      if (editing) {
        if (!file) body.delete("file");
        await api.patch(`/documents/${editing.id}/`, body);
      } else {
        if (!file) {
          setError("Choose a file to upload.");
          return;
        }
        await api.post("/documents/", body);
      }
      setOpen(false);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || JSON.stringify(e.response?.data) || e.message);
    }
  };

  const remove = async (doc) => {
    if (!window.confirm(`Delete "${doc.title}"?`)) return;
    await api.delete(`/documents/${doc.id}/`);
    load();
  };

  const download = async (doc) => {
    const res = await api.get(`/documents/${doc.id}/download/`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.original_filename || `${doc.title}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const kindLabel = useMemo(
    () => Object.fromEntries(KINDS.map((k) => [k.value, k.label])),
    []
  );

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Documents
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          Upload
        </Button>
      </Stack>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
        <TextField
          select
          label="Scope"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          size="small"
          sx={{ minWidth: 160 }}
        >
          {SCOPES.map((s) => (
            <MenuItem key={s.value || "all"} value={s.value}>
              {s.label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Kind"
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
          size="small"
          sx={{ minWidth: 180 }}
        >
          <MenuItem value="">All kinds</MenuItem>
          {KINDS.map((k) => (
            <MenuItem key={k.value} value={k.value}>
              {k.label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Client"
          value={clientFilter}
          onChange={(e) => setClientFilter(e.target.value)}
          size="small"
          sx={{ minWidth: 220 }}
          disabled={scope === "personal"}
        >
          <MenuItem value="">All clients</MenuItem>
          {clients.map((c) => (
            <MenuItem key={c.id} value={c.id}>
              {c.name}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {typeof error === "string" ? error : JSON.stringify(error)}
        </Alert>
      )}

      <Stack spacing={1}>
        {docs.map((doc) => (
          <Paper
            key={doc.id}
            variant="outlined"
            sx={{ p: 1.5, display: "flex", alignItems: "center", gap: 2 }}
          >
            <DescriptionIcon color="action" />
            <Box sx={{ flexGrow: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Typography sx={{ fontWeight: 600 }}>{doc.title}</Typography>
                <Chip size="small" label={kindLabel[doc.kind] || doc.kind} />
                <Chip
                  size="small"
                  variant="outlined"
                  label={doc.client_label || "Personal"}
                  color={doc.client ? "primary" : "default"}
                />
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {[doc.document_date, doc.original_filename].filter(Boolean).join(" · ")}
              </Typography>
              {doc.notes && (
                <Typography variant="body2" color="text.secondary">
                  {doc.notes}
                </Typography>
              )}
            </Box>
            <IconButton size="small" onClick={() => download(doc)} title="Download">
              <DownloadIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" onClick={() => openEdit(doc)}>
              <EditIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" color="error" onClick={() => remove(doc)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Paper>
        ))}
        {docs.length === 0 && (
          <Typography color="text.secondary">No documents yet.</Typography>
        )}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{editing ? "Edit document" : "Upload document"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              select
              label="Client"
              value={form.client}
              onChange={(e) => setForm({ ...form, client: e.target.value })}
              fullWidth
              helperText="Leave empty for personal documents (tax, certificates…)"
            >
              <MenuItem value="">Personal (no client)</MenuItem>
              {clients.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.name}
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
              label="Title"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              fullWidth
              autoFocus
            />
            <TextField
              label="Document date"
              type="date"
              InputLabelProps={{ shrink: true }}
              value={form.document_date}
              onChange={(e) => setForm({ ...form, document_date: e.target.value })}
              fullWidth
            />
            <Button variant="outlined" component="label">
              {file
                ? file.name
                : editing
                  ? `Replace file (current: ${editing.original_filename || "—"})`
                  : "Choose file"}
              <input
                hidden
                type="file"
                onChange={(e) => {
                  const f = e.target.files?.[0] || null;
                  setFile(f);
                  if (f && !form.title.trim()) {
                    setForm((prev) => ({ ...prev, title: f.name.replace(/\.[^.]+$/, "") }));
                  }
                }}
              />
            </Button>
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
          <Button
            variant="contained"
            onClick={save}
            disabled={!form.title.trim() || (!editing && !file)}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
