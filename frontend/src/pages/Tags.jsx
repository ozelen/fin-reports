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
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import api from "../api";

const BLANK = { name: "", color: "#1f4e78", description: "" };

export default function Tags() {
  const [tags, setTags] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);

  const load = async () => {
    const { data } = await api.get("/tags/", { params: { page_size: 200 } });
    setTags(data.results);
  };

  useEffect(() => {
    load();
  }, []);

  const openNew = () => {
    setEditing(null);
    setForm(BLANK);
    setOpen(true);
  };

  const openEdit = (tag) => {
    setEditing(tag);
    setForm({ name: tag.name, color: tag.color, description: tag.description || "" });
    setOpen(true);
  };

  const save = async () => {
    if (editing) await api.patch(`/tags/${editing.id}/`, form);
    else await api.post("/tags/", form);
    setOpen(false);
    load();
  };

  const remove = async (tag) => {
    await api.delete(`/tags/${tag.id}/`);
    load();
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Tags
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          New tag
        </Button>
      </Stack>

      <Stack spacing={1}>
        {tags.map((t) => (
          <Paper
            key={t.id}
            variant="outlined"
            sx={{ p: 1.5, display: "flex", alignItems: "center", gap: 2 }}
          >
            <Chip label={t.name} sx={{ bgcolor: t.color, color: "#fff", fontWeight: 600 }} />
            <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1 }}>
              {t.description}
            </Typography>
            <Chip size="small" variant="outlined" label={`${t.transaction_count} tx`} />
            <IconButton size="small" onClick={() => openEdit(t)}>
              <EditIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" color="error" onClick={() => remove(t)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Paper>
        ))}
        {tags.length === 0 && (
          <Typography color="text.secondary">No tags yet.</Typography>
        )}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>{editing ? "Edit tag" : "New tag"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              autoFocus
              fullWidth
            />
            <Stack direction="row" spacing={2} alignItems="center">
              <TextField
                label="Color"
                type="color"
                value={form.color}
                onChange={(e) => setForm({ ...form, color: e.target.value })}
                sx={{ width: 90 }}
              />
              <Chip label={form.name || "preview"} sx={{ bgcolor: form.color, color: "#fff" }} />
            </Stack>
            <TextField
              label="Description"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              helperText="Helps the AI classifier understand this tag."
              multiline
              minRows={2}
              fullWidth
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
