import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  IconButton,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import api from "../api";
import CriteriaFields from "../components/CriteriaFields";
import TagMultiSelect from "../components/TagMultiSelect";

const BLANK = {
  name: "",
  order: 0,
  is_active: true,
  criteria: {},
  regex: "",
  stop_processing: false,
  tags: [],
};

export default function Rules() {
  const [rules, setRules] = useState([]);
  const [tags, setTags] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [preview, setPreview] = useState(null);
  const [feedback, setFeedback] = useState(null);

  const load = async () => {
    const [r, t] = await Promise.all([
      api.get("/rules/", { params: { page_size: 200 } }),
      api.get("/tags/", { params: { page_size: 200 } }),
    ]);
    setRules(r.data.results);
    setTags(t.data.results);
  };

  useEffect(() => {
    load();
  }, []);

  const openNew = () => {
    setEditing(null);
    setForm(BLANK);
    setPreview(null);
    setOpen(true);
  };

  const openEdit = (rule) => {
    setEditing(rule);
    setForm({
      name: rule.name,
      order: rule.order,
      is_active: rule.is_active,
      criteria: rule.criteria || {},
      regex: rule.regex || "",
      stop_processing: rule.stop_processing,
      tags: rule.tags || [],
    });
    setPreview(null);
    setOpen(true);
  };

  const save = async () => {
    if (editing) await api.patch(`/rules/${editing.id}/`, form);
    else await api.post("/rules/", form);
    setOpen(false);
    load();
  };

  const remove = async (rule) => {
    await api.delete(`/rules/${rule.id}/`);
    load();
  };

  const runPreview = async () => {
    let ruleId = editing?.id;
    if (!ruleId) {
      const { data } = await api.post("/rules/", form);
      setEditing(data);
      ruleId = data.id;
    } else {
      await api.patch(`/rules/${ruleId}/`, form);
    }
    const { data } = await api.get(`/rules/${ruleId}/preview/`);
    setPreview(data);
    load();
  };

  const applyAll = async () => {
    const { data } = await api.post("/rules/apply/", {});
    setFeedback(
      `Applied rules: ${data.assignments_created} tag assignment(s) across ${data.transactions_matched} transaction(s).`,
    );
    load();
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="flex-end" alignItems="center" sx={{ mb: 2 }}>
        <Stack direction="row" spacing={1}>
          <Button startIcon={<PlayArrowIcon />} onClick={applyAll}>
            Apply all now
          </Button>
          <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
            New rule
          </Button>
        </Stack>
      </Stack>

      {feedback && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setFeedback(null)}>
          {feedback}
        </Alert>
      )}

      <Stack spacing={1}>
        {rules.map((r) => (
          <Paper key={r.id} variant="outlined" sx={{ p: 1.5, display: "flex", alignItems: "center", gap: 2 }}>
            <Chip size="small" label={`#${r.order}`} />
            <Typography sx={{ fontWeight: 600, minWidth: 140 }}>{r.name}</Typography>
            <Stack direction="row" spacing={0.5} sx={{ flexGrow: 1, flexWrap: "wrap" }}>
              {(r.tags || []).map((id) => {
                const tag = tags.find((t) => t.id === id);
                return (
                  <Chip
                    key={id}
                    size="small"
                    label={tag?.name || id}
                    sx={{ bgcolor: tag?.color, color: "#fff" }}
                  />
                );
              })}
            </Stack>
            {!r.is_active && <Chip size="small" color="warning" label="inactive" />}
            <IconButton size="small" onClick={() => openEdit(r)}>
              <EditIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" color="error" onClick={() => remove(r)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Paper>
        ))}
        {rules.length === 0 && <Typography color="text.secondary">No rules yet.</Typography>}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{editing ? "Edit rule" : "New rule"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Stack direction="row" spacing={2}>
              <TextField
                label="Name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                fullWidth
              />
              <TextField
                label="Order"
                type="number"
                value={form.order}
                onChange={(e) => setForm({ ...form, order: Number(e.target.value) })}
                sx={{ width: 110 }}
              />
            </Stack>

            <Typography variant="subtitle2" color="text.secondary">
              Match transactions where
            </Typography>
            <CriteriaFields
              value={form.criteria}
              onChange={(criteria) => setForm({ ...form, criteria })}
            />
            <TextField
              label="Regex on concept (optional)"
              value={form.regex}
              onChange={(e) => setForm({ ...form, regex: e.target.value })}
              fullWidth
            />

            <Divider />
            <Typography variant="subtitle2" color="text.secondary">
              Then assign tags
            </Typography>
            <TagMultiSelect
              tags={tags}
              value={form.tags}
              onChange={(v) => setForm({ ...form, tags: v })}
            />

            <Stack direction="row" spacing={2}>
              <FormControlLabel
                control={
                  <Switch
                    checked={form.is_active}
                    onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                  />
                }
                label="Active"
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={form.stop_processing}
                    onChange={(e) => setForm({ ...form, stop_processing: e.target.checked })}
                  />
                }
                label="Stop after match"
              />
            </Stack>

            {preview && (
              <Alert severity="info">
                Matches <strong>{preview.match_count}</strong> transaction(s).
                {preview.sample?.length > 0 && (
                  <Box sx={{ mt: 1 }}>
                    {preview.sample.slice(0, 5).map((t) => (
                      <Typography key={t.id} variant="caption" display="block" noWrap>
                        {t.operation_date} · {t.counterparty || t.concept.slice(0, 50)}
                      </Typography>
                    ))}
                  </Box>
                )}
              </Alert>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={runPreview}>Preview matches</Button>
          <Box sx={{ flexGrow: 1 }} />
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={save} disabled={!form.name.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
