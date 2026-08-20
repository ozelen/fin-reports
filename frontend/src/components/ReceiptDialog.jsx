import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
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

  useEffect(() => {
    if (!receiptId) return;
    setError("");
    setPreview("");
    setReceipt(null);
    setItems([]);
    let objectUrl = "";
    let cancelled = false;
    api
      .get(`/receipts/${receiptId}/`)
      .then(async ({ data }) => {
        if (cancelled) return;
        setReceipt(data);
        setItems(data.items || []);
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
      })
      .catch((e) => {
        if (!cancelled) setError(e.response?.data?.detail || e.message);
      });
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
            ? `${receipt.merchant || "Receipt"} · ${money(receipt.amount, receipt.currency)}`
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
                {preview && (
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
                )}
                <Stack spacing={0.5} sx={{ minWidth: 200 }}>
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
                </Stack>
              </Stack>
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
