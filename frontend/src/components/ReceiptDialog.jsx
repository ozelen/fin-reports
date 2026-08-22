import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";
import api from "../api";
import { TagCell, TagEditorPopover } from "./TagCell";

const money = (v, code) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("es-ES", {
        style: "currency",
        currency: code || "EUR",
      }).format(v);

const KNOWN = ["time", "location", "payment_method", "card_last4"];

function isPdf(receipt) {
  const name = (receipt.original_filename || "").toLowerCase();
  const mime = (receipt.mime_type || "").toLowerCase();
  return name.endsWith(".pdf") || mime.includes("pdf");
}

function factRows(receipt) {
  const d = receipt.details || {};
  const rows = [];
  if (receipt.document_date) rows.push(["Date", receipt.document_date]);
  if (d.time) rows.push(["Time", d.time]);
  if (d.location) rows.push(["Location", d.location]);
  if (d.payment_method || d.card_last4) {
    const pay = [
      d.payment_method,
      d.card_last4 && `····${String(d.card_last4).slice(-4)}`,
    ]
      .filter(Boolean)
      .join(" ");
    rows.push(["Payment", pay]);
  }
  for (const [key, value] of Object.entries(d)) {
    if (KNOWN.includes(key)) continue;
    rows.push([key.replace(/_/g, " "), String(value)]);
  }
  if (receipt.notes) rows.push(["Notes", receipt.notes]);
  return rows;
}

export default function ReceiptDialog({
  receiptId,
  allTags = [],
  onClose,
  onSaved,
  onTagsChanged,
}) {
  const [receipt, setReceipt] = useState(null);
  const [items, setItems] = useState([]);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [tagEditor, setTagEditor] = useState(null);
  const [form, setForm] = useState({ merchant: "", amount: "", document_date: "" });
  const [matches, setMatches] = useState([]);
  const [saving, setSaving] = useState(false);

  const loadReceipt = async (id) => {
    const { data } = await api.get(`/receipts/${id}/`);
    setReceipt(data);
    setItems(data.items || []);
    setForm({
      merchant: data.merchant || "",
      amount: data.amount ?? "",
      document_date: data.document_date || "",
    });
    return data;
  };

  useEffect(() => {
    if (!receiptId) return;
    setError("");
    setPreview("");
    setReceipt(null);
    setItems([]);
    setMatches([]);
    let objectUrl = "";
    let cancelled = false;
    (async () => {
      try {
        const data = await loadReceipt(receiptId);
        if (cancelled) return;
        if (data.file_url) {
          const res = await api.get(`/receipts/${receiptId}/download/`, {
            responseType: "blob",
          });
          objectUrl = URL.createObjectURL(res.data);
          if (cancelled) {
            URL.revokeObjectURL(objectUrl);
            return;
          }
          setPreview(objectUrl);
        }
        if (data.kind === "invoice" && !data.paid) {
          const { data: hits } = await api.get(`/receipts/${receiptId}/matches/`);
          if (!cancelled) {
            setMatches(Array.isArray(hits) ? hits : hits?.results || []);
          }
        }
      } catch (e) {
        if (!cancelled) setError(e.response?.data?.detail || e.message);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [receiptId]);

  const setItemTags = (id, updater) =>
    setItems((rows) =>
      rows.map((r) => (r.id === id ? { ...r, tags: updater(r.tags || []) } : r)),
    );

  const addTagToItem = async (row, tag) => {
    await api.post(`/purchase-items/${row.id}/tag/`, { add: [tag.id] });
    setItemTags(row.id, (cur) =>
      cur.some((t) => t.id === tag.id)
        ? cur
        : [...cur, { id: tag.id, name: tag.name, color: tag.color }],
    );
    onSaved?.();
  };

  const removeTagFromItem = async (row, tagId) => {
    await api.post(`/purchase-items/${row.id}/tag/`, { remove: [tagId] });
    setItemTags(row.id, (cur) => cur.filter((t) => t.id !== tagId));
    onSaved?.();
  };

  const createAndAddTag = async (row, name) => {
    const existing = allTags.find((t) => t.name.toLowerCase() === name.toLowerCase());
    const tag = existing || (await api.post("/tags/", { name })).data;
    await addTagToItem(row, tag);
    if (!existing) onTagsChanged?.();
  };

  const processRowUpdate = async (newRow) => {
    setError("");
    await api.patch(`/purchase-items/${newRow.id}/`, {
      name: newRow.name,
      title: newRow.title,
      quantity: newRow.quantity,
      amount: newRow.amount === "" ? null : newRow.amount,
    });
    setItems((rows) => rows.map((r) => (r.id === newRow.id ? { ...r, ...newRow } : r)));
    return newRow;
  };

  const saveInvoice = async () => {
    setError("");
    setSaving(true);
    try {
      await api.patch(`/receipts/${receiptId}/`, {
        merchant: form.merchant,
        amount: form.amount === "" ? null : form.amount,
        document_date: form.document_date || null,
      });
      const data = await loadReceipt(receiptId);
      onSaved?.();
      if (data.kind === "invoice" && !data.paid) {
        const { data: hits } = await api.get(`/receipts/${receiptId}/matches/`);
        setMatches(hits);
      } else {
        setMatches([]);
      }
    } catch (e) {
      setError(e.response?.data?.detail || JSON.stringify(e.response?.data) || e.message);
    } finally {
      setSaving(false);
    }
  };

  const attachMatch = async (txId) => {
    setError("");
    setSaving(true);
    try {
      await api.post(`/receipts/${receiptId}/attach/`, { transaction: txId });
      await loadReceipt(receiptId);
      setMatches([]);
      onSaved?.();
    } catch (e) {
      setError(e.response?.data?.detail || JSON.stringify(e.response?.data) || e.message);
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    { field: "title", headerName: "Title", flex: 1, minWidth: 140, editable: true },
    { field: "name", headerName: "Printed", flex: 1, minWidth: 140, editable: true },
    { field: "quantity", headerName: "Qty", width: 80, type: "number", editable: true },
    {
      field: "amount",
      headerName: "Amount",
      width: 120,
      type: "number",
      editable: true,
      renderCell: (p) => (
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {money(p.value, receipt?.currency)}
        </Typography>
      ),
    },
    {
      field: "tags",
      headerName: "Tags",
      width: 260,
      sortable: false,
      renderCell: (p) => (
        <TagCell
          row={p.row}
          onOpen={(anchorEl, row) => setTagEditor({ anchorEl, rowId: row.id })}
          onRemove={removeTagFromItem}
        />
      ),
    },
  ];

  const facts = receipt ? factRows(receipt) : [];

  return (
    <>
      <Dialog
        open={Boolean(receiptId)}
        onClose={onClose}
        fullWidth
        maxWidth="lg"
        disableEnforceFocus
      >
        <DialogTitle>
          {receipt
            ? `${receipt.kind === "invoice" ? "Invoice" : "Receipt"} · ${receipt.merchant || receipt.original_filename || `#${receipt.id}`} · ${money(receipt.amount, receipt.currency)}`
            : "Receipt"}
        </DialogTitle>
        <DialogContent dividers>
          {error && (
            <Typography color="error" sx={{ mb: 1 }}>
              {error}
            </Typography>
          )}
          {receipt && (
            <Stack spacing={2}>
              <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                {preview &&
                  (isPdf(receipt) ? (
                    <Box
                      component="iframe"
                      src={preview}
                      title={receipt.original_filename || "invoice"}
                      sx={{
                        height: 360,
                        width: { xs: "100%", md: 280 },
                        border: 0,
                        borderRadius: 1,
                        bgcolor: "grey.100",
                        alignSelf: "flex-start",
                      }}
                    />
                  ) : (
                    <Box
                      component="img"
                      src={preview}
                      alt={receipt.original_filename || "receipt"}
                      sx={{
                        maxHeight: 360,
                        maxWidth: { md: 280 },
                        objectFit: "contain",
                        borderRadius: 1,
                        bgcolor: "grey.100",
                        alignSelf: "flex-start",
                      }}
                    />
                  ))}
                <Stack spacing={1} sx={{ minWidth: 200, flex: 1 }}>
                  {receipt.kind === "invoice" && (
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Chip
                        size="small"
                        color={
                          receipt.status === "paid"
                            ? "success"
                            : receipt.status === "overdue"
                              ? "error"
                              : "warning"
                        }
                        label={
                          receipt.status === "paid"
                            ? "Paid"
                            : receipt.status === "overdue"
                              ? "Overdue"
                              : "Unpaid"
                        }
                      />
                    </Stack>
                  )}
                  {receipt.kind === "invoice" ? (
                    <>
                      <TextField
                        label="Merchant"
                        size="small"
                        value={form.merchant}
                        onChange={(e) => setForm({ ...form, merchant: e.target.value })}
                      />
                      <TextField
                        label="Amount"
                        size="small"
                        type="number"
                        value={form.amount}
                        onChange={(e) => setForm({ ...form, amount: e.target.value })}
                      />
                      <TextField
                        label="Date"
                        size="small"
                        type="date"
                        InputLabelProps={{ shrink: true }}
                        value={form.document_date}
                        onChange={(e) =>
                          setForm({ ...form, document_date: e.target.value })
                        }
                      />
                      <Button
                        variant="contained"
                        size="small"
                        onClick={saveInvoice}
                        disabled={saving}
                        sx={{ alignSelf: "flex-start" }}
                      >
                        Save & match
                      </Button>
                    </>
                  ) : (
                    <>
                      {facts.map(([label, value]) => (
                        <Typography key={label} variant="body2">
                          <Box component="span" sx={{ color: "text.secondary", mr: 1 }}>
                            {label}
                          </Box>
                          {value}
                        </Typography>
                      ))}
                      {facts.length === 0 && (
                        <Typography variant="body2" color="text.secondary">
                          No extra details parsed.
                        </Typography>
                      )}
                    </>
                  )}
                  {receipt.kind === "invoice" && !receipt.paid && matches.length > 0 && (
                    <Stack spacing={0.5}>
                      <Typography variant="body2" color="text.secondary">
                        Matching transactions — click to mark paid
                      </Typography>
                      {matches.map((tx) => (
                        <Button
                          key={tx.id}
                          size="small"
                          variant="outlined"
                          disabled={saving}
                          onClick={() => attachMatch(tx.id)}
                          sx={{ justifyContent: "flex-start", textTransform: "none" }}
                        >
                          #{tx.id} {tx.operation_date} {money(tx.amount, tx.currency)}{" "}
                          {(tx.counterparty || tx.concept || "").slice(0, 48)}
                        </Button>
                      ))}
                    </Stack>
                  )}
                </Stack>
              </Stack>
              {items.length > 0 && (
                <DataGrid
                  autoHeight
                  rows={items}
                  columns={columns}
                  hideFooter
                  disableRowSelectionOnClick
                  getRowHeight={() => "auto"}
                  processRowUpdate={processRowUpdate}
                  onProcessRowUpdateError={(e) =>
                    setError(e.response?.data?.detail || e.message)
                  }
                  sx={{ bgcolor: "background.paper", "& .MuiDataGrid-cell": { py: 0.5 } }}
                />
              )}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Close</Button>
        </DialogActions>
      </Dialog>
      <TagEditorPopover
        anchorEl={tagEditor?.anchorEl}
        row={items.find((r) => r.id === tagEditor?.rowId)}
        allTags={allTags}
        onClose={() => setTagEditor(null)}
        onAddExisting={addTagToItem}
        onCreateAndAdd={createAndAddTag}
      />
    </>
  );
}
