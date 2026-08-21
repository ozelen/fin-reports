import { useEffect, useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
} from "@mui/material";
import api from "../api";
import TagMultiSelect from "./TagMultiSelect";

export const FREQS = [
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
  { value: "quarter", label: "Quarterly" },
  { value: "year", label: "Yearly" },
];
export const CATS = [
  { value: "subscription", label: "Subscription" },
  { value: "loan", label: "Loan" },
  { value: "tax", label: "Tax" },
  { value: "income", label: "Income" },
  { value: "other", label: "Other" },
];
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const todayIso = () => new Date().toISOString().slice(0, 10);

const BLANK = {
  name: "",
  amount: "",
  currency: "EUR",
  frequency: "month",
  due_day: 1,
  start_date: todayIso(),
  end_date: "",
  account: "",
  match_text: "",
  amount_tolerance_pct: 10,
  auto_match: true,
  category: "other",
  is_active: true,
  tags: [],
};

export function formFromRecurrence(row) {
  if (!row) return { ...BLANK, start_date: todayIso() };
  return {
    name: row.name || "",
    amount: row.amount ?? "",
    currency: row.currency || "EUR",
    frequency: row.frequency || "month",
    due_day: row.due_day ?? 1,
    start_date: row.start_date || todayIso(),
    end_date: row.end_date || "",
    account: row.account || "",
    match_text: row.match_text || "",
    amount_tolerance_pct: row.amount_tolerance_pct ?? 10,
    auto_match: row.auto_match !== false,
    category: row.category || "other",
    is_active: row.is_active !== false,
    tags: row.tags || [],
  };
}

export default function RecurrenceDialog({
  open,
  recurrence,
  tags,
  accounts,
  onClose,
  onSaved,
}) {
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setForm(formFromRecurrence(recurrence));
  }, [open, recurrence]);

  const payload = () => ({
    ...form,
    due_day: Number(form.due_day),
    account: form.account || null,
    end_date: form.end_date || null,
    amount_tolerance_pct: Number(form.amount_tolerance_pct),
  });

  const save = async () => {
    setSaving(true);
    try {
      const body = payload();
      const { data } = recurrence?.id
        ? await api.patch(`/recurrences/${recurrence.id}/`, body)
        : await api.post("/recurrences/", body);
      onSaved?.(data);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{recurrence?.id ? "Edit recurrence" : "New recurrence"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            fullWidth
          />
          <Stack direction="row" spacing={2}>
            <TextField
              label="Amount"
              type="number"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              fullWidth
              helperText="Negative for expenses"
            />
            <TextField
              select
              label="Category"
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              sx={{ minWidth: 160 }}
            >
              {CATS.map((c) => (
                <MenuItem key={c.value} value={c.value}>
                  {c.label}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField
              select
              label="Frequency"
              value={form.frequency}
              onChange={(e) => setForm({ ...form, frequency: e.target.value })}
              sx={{ minWidth: 160 }}
            >
              {FREQS.map((f) => (
                <MenuItem key={f.value} value={f.value}>
                  {f.label}
                </MenuItem>
              ))}
            </TextField>
            {form.frequency === "week" ? (
              <TextField
                select
                label="Weekday"
                value={form.due_day}
                onChange={(e) => setForm({ ...form, due_day: Number(e.target.value) })}
                sx={{ minWidth: 140 }}
              >
                {WEEKDAYS.map((d, i) => (
                  <MenuItem key={d} value={i}>
                    {d}
                  </MenuItem>
                ))}
              </TextField>
            ) : (
              <TextField
                label="Due day"
                type="number"
                value={form.due_day}
                onChange={(e) => setForm({ ...form, due_day: e.target.value })}
                inputProps={{ min: 1, max: 31 }}
                sx={{ width: 120 }}
              />
            )}
            <TextField
              select
              label="Account"
              value={form.account}
              onChange={(e) => setForm({ ...form, account: e.target.value })}
              sx={{ minWidth: 160 }}
            >
              <MenuItem value="">Any</MenuItem>
              {accounts.map((a) => (
                <MenuItem key={a.id} value={a.id}>
                  {a.name}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField
              label="Start"
              type="date"
              value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="End (optional)"
              type="date"
              value={form.end_date}
              onChange={(e) => setForm({ ...form, end_date: e.target.value })}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
          </Stack>
          <TextField
            label="Match text"
            value={form.match_text}
            onChange={(e) => setForm({ ...form, match_text: e.target.value })}
            helperText="Counterparty / merchant fingerprint used when statements arrive"
            fullWidth
          />
          <TextField
            label="Amount tolerance %"
            type="number"
            value={form.amount_tolerance_pct}
            onChange={(e) => setForm({ ...form, amount_tolerance_pct: e.target.value })}
          />
          <TagMultiSelect
            tags={tags}
            value={form.tags}
            onChange={(v) => setForm({ ...form, tags: v })}
          />
          <Stack direction="row" spacing={2}>
            <FormControlLabel
              control={
                <Switch
                  checked={form.auto_match}
                  onChange={(e) => setForm({ ...form, auto_match: e.target.checked })}
                />
              }
              label="Auto-match incoming"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                />
              }
              label="Active"
            />
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={save}
          disabled={saving || !form.name.trim() || form.amount === ""}
        >
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
