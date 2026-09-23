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
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";
import { useParams } from "react-router-dom";
import api from "../api";

const PERSONAL_KINDS = [
  { value: "tax_declaration", label: "Tax declaration" },
  { value: "tax_certificate", label: "Tax certificate" },
  { value: "other", label: "Other" },
];

const CLIENT_KINDS = [
  { value: "agreement", label: "Agreement" },
  { value: "order", label: "Order" },
  { value: "offer", label: "Offer" },
  { value: "other", label: "Other" },
];

const BLANK = {
  kind: "other",
  title: "",
  document_date: "",
  starts_on: "",
  ends_on: "",
  notes: "",
};

export default function Documents() {
  const { clientId } = useParams();
  const personal = !clientId;
  const kinds = personal ? PERSONAL_KINDS : CLIENT_KINDS;

  const [docs, setDocs] = useState([]);
  const [kindFilter, setKindFilter] = useState("");
  const [error, setError] = useState("");

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [file, setFile] = useState(null);

  const load = async () => {
    const params = { page_size: 200 };
    if (personal) params.scope = "personal";
    else params.client = clientId;
    if (kindFilter) params.kind = kindFilter;
    const { data } = await api.get("/documents/", { params });
    setDocs(data.results);
  };

  useEffect(() => {
    load().catch((e) => setError(e.response?.data?.detail || e.message));
  }, [clientId, kindFilter, personal]);

  const openNew = () => {
    setEditing(null);
    setForm({
      ...BLANK,
      kind: personal ? "tax_declaration" : "agreement",
    });
    setFile(null);
    setOpen(true);
  };

  const openEdit = (doc) => {
    setEditing(doc);
    setForm({
      kind: doc.kind,
      title: doc.title,
      document_date: doc.document_date || "",
      starts_on: doc.starts_on || "",
      ends_on: doc.ends_on || "",
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
    body.append("document_date", form.document_date || "");
    if (!personal) {
      body.append("starts_on", form.starts_on || "");
      body.append("ends_on", form.ends_on || "");
    }
    if (personal) body.append("client", "");
    else body.append("client", clientId);
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

  const download = async (doc, redacted = false) => {
    try {
      const res = await api.get(`/documents/${doc.id}/download/`, {
        params: redacted ? { redacted: 1 } : undefined,
        responseType: "blob",
      });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      const base = doc.original_filename || `${doc.title}.pdf`;
      a.download = redacted ? base.replace(/(\.[^.]+)?$/, "-redacted$1") : base;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      const blob = e.response?.data;
      if (blob instanceof Blob) {
        try {
          const body = JSON.parse(await blob.text());
          setError(body.detail || "Download failed.");
          return;
        } catch {
          /* not json */
        }
      }
      setError(e.response?.data?.detail || e.message || "Download failed.");
    }
  };

  const kindLabel = useMemo(
    () => Object.fromEntries([...PERSONAL_KINDS, ...CLIENT_KINDS].map((k) => [k.value, k.label])),
    []
  );

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <TextField
          select
          label="Kind"
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
          size="small"
          sx={{ minWidth: 180 }}
        >
          <MenuItem value="">All kinds</MenuItem>
          {kinds.map((k) => (
            <MenuItem key={k.value} value={k.value}>
              {k.label}
            </MenuItem>
          ))}
        </TextField>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          Upload
        </Button>
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
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {[
                  doc.starts_on || doc.ends_on
                    ? `${doc.starts_on || "…"} → ${doc.ends_on || "open"}`
                    : doc.document_date,
                  doc.original_filename,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </Typography>
              {doc.notes && (
                <Typography variant="body2" color="text.secondary">
                  {doc.notes}
                </Typography>
              )}
            </Box>
            <IconButton size="small" onClick={() => download(doc)} title="Download original">
              <DownloadIcon fontSize="small" />
            </IconButton>
            <IconButton
              size="small"
              onClick={() => download(doc, true)}
              title="Download redacted (no bank details or amounts)"
            >
              <VisibilityOffIcon fontSize="small" />
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
              label="Kind"
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}
              fullWidth
            >
              {kinds.map((k) => (
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
              label={form.kind === "agreement" ? "Signed on" : "Document date"}
              type="date"
              InputLabelProps={{ shrink: true }}
              value={form.document_date}
              onChange={(e) => {
                const document_date = e.target.value;
                setForm((prev) => ({
                  ...prev,
                  document_date,
                  starts_on:
                    !personal && form.kind === "agreement" && !prev.starts_on
                      ? document_date
                      : prev.starts_on,
                }));
              }}
              fullWidth
            />
            {!personal && (
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                <TextField
                  label="Start date"
                  type="date"
                  InputLabelProps={{ shrink: true }}
                  value={form.starts_on}
                  onChange={(e) => setForm({ ...form, starts_on: e.target.value })}
                  fullWidth
                />
                <TextField
                  label="Termination date"
                  type="date"
                  InputLabelProps={{ shrink: true }}
                  value={form.ends_on}
                  onChange={(e) => setForm({ ...form, ends_on: e.target.value })}
                  helperText="Leave empty if still open"
                  fullWidth
                />
              </Stack>
            )}
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
