import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { SimpleTreeView } from "@mui/x-tree-view/SimpleTreeView";
import { TreeItem } from "@mui/x-tree-view/TreeItem";
import AddIcon from "@mui/icons-material/Add";
import CreateNewFolderIcon from "@mui/icons-material/CreateNewFolder";
import DeleteIcon from "@mui/icons-material/Delete";
import DownloadIcon from "@mui/icons-material/Download";
import EditIcon from "@mui/icons-material/Edit";
import FolderIcon from "@mui/icons-material/Folder";
import ListIcon from "@mui/icons-material/List";
import { DataGrid } from "@mui/x-data-grid";
import api from "../api";
import CriteriaFields from "../components/CriteriaFields";
import TagMultiSelect from "../components/TagMultiSelect";

const currency = (v, code) =>
  v == null
    ? ""
    : new Intl.NumberFormat("es-ES", { style: "currency", currency: code || "EUR" }).format(v);

const BLANK = { name: "", parent: null, tags: [], tag_match: "any", criteria: {} };

function flatten(nodes, depth = 0, acc = []) {
  for (const n of nodes) {
    acc.push({ ...n, depth });
    if (n.children?.length) flatten(n.children, depth + 1, acc);
  }
  return acc;
}

function allIds(nodes, acc = []) {
  for (const n of nodes) {
    acc.push(String(n.id));
    if (n.children?.length) allIds(n.children, acc);
  }
  return acc;
}

export default function Folders() {
  const [tree, setTree] = useState([]);
  const [tags, setTags] = useState([]);
  const [totals, setTotals] = useState("both");
  const [recursive, setRecursive] = useState(true);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);

  const [viewFolder, setViewFolder] = useState(null);
  const [viewRows, setViewRows] = useState([]);
  const [viewSelection, setViewSelection] = useState([]);
  const [viewLoading, setViewLoading] = useState(false);

  const load = useCallback(async () => {
    const [t, tg] = await Promise.all([
      api.get("/folders/tree/"),
      api.get("/tags/", { params: { page_size: 200 } }),
    ]);
    setTree(t.data);
    setTags(tg.data.results);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const flat = useMemo(() => flatten(tree), [tree]);
  const expanded = useMemo(() => allIds(tree), [tree]);

  const openNew = (parent = null) => {
    setEditing(null);
    setForm({ ...BLANK, parent });
    setEditorOpen(true);
  };

  const openEdit = (folder) => {
    setEditing(folder);
    setForm({
      name: folder.name,
      parent: folder.parent,
      tags: folder.tags || [],
      tag_match: folder.tag_match || "any",
      criteria: folder.criteria || {},
    });
    setEditorOpen(true);
  };

  const save = async () => {
    const payload = { ...form };
    if (editing) await api.patch(`/folders/${editing.id}/`, payload);
    else await api.post("/folders/", payload);
    setEditorOpen(false);
    load();
  };

  const remove = async (folder) => {
    await api.delete(`/folders/${folder.id}/`);
    load();
  };

  const exportFolder = async (folder) => {
    const res = await api.get(`/folders/${folder.id}/export/`, {
      params: { totals, recursive },
      responseType: "blob",
    });
    const disposition = res.headers["content-disposition"] || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : `${folder.name}.xlsx`;
    const url = window.URL.createObjectURL(new Blob([res.data]));
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  };

  const openView = async (folder) => {
    setViewFolder(folder);
    setViewSelection([]);
    setViewLoading(true);
    try {
      const { data } = await api.get(`/folders/${folder.id}/transactions/`, {
        params: { page_size: 500, recursive: true },
      });
      setViewRows(data.results || data);
    } finally {
      setViewLoading(false);
    }
  };

  const removeFromFolder = async () => {
    if (!viewFolder || !viewSelection.length) return;
    await api.post(`/folders/${viewFolder.id}/update-transactions/`, {
      remove: viewSelection,
    });
    openView(viewFolder);
    load();
  };

  const renderTree = (nodes) =>
    nodes.map((node) => (
      <TreeItem
        key={node.id}
        itemId={String(node.id)}
        label={
          <Stack direction="row" alignItems="center" spacing={1} sx={{ py: 0.5 }}>
            <FolderIcon color="primary" fontSize="small" />
            <Typography sx={{ fontWeight: 600 }}>{node.name}</Typography>
            <Chip size="small" label={node.transaction_count} />
            {(node.tags || []).map((id) => {
              const tag = tags.find((t) => t.id === id);
              return tag ? (
                <Chip key={id} size="small" label={tag.name} sx={{ bgcolor: tag.color, color: "#fff" }} />
              ) : null;
            })}
            <Box sx={{ flexGrow: 1 }} />
            <Actions
              onAction={(fn) => (e) => {
                e.stopPropagation();
                fn();
              }}
              node={node}
              onAddChild={() => openNew(node.id)}
              onView={() => openView(node)}
              onEdit={() => openEdit(node)}
              onExport={() => exportFolder(node)}
              onDelete={() => remove(node)}
            />
          </Stack>
        }
      >
        {node.children?.length ? renderTree(node.children) : null}
      </TreeItem>
    ));

  return (
    <Box>
      <Stack direction="row" justifyContent="flex-end" alignItems="center" sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        <Stack direction="row" spacing={2} alignItems="center">
          <TextField select size="small" label="Export totals" value={totals} onChange={(e) => setTotals(e.target.value)} sx={{ minWidth: 160 }}>
            <MenuItem value="both">Income + Expenses</MenuItem>
            <MenuItem value="income">Income only</MenuItem>
            <MenuItem value="expense">Expenses only</MenuItem>
          </TextField>
          <TextField select size="small" label="Scope" value={recursive ? "1" : "0"} onChange={(e) => setRecursive(e.target.value === "1")} sx={{ minWidth: 150 }}>
            <MenuItem value="1">Include subfolders</MenuItem>
            <MenuItem value="0">This folder only</MenuItem>
          </TextField>
          <Button variant="contained" startIcon={<CreateNewFolderIcon />} onClick={() => openNew(null)}>
            New folder
          </Button>
        </Stack>
      </Stack>

      <Paper variant="outlined" sx={{ p: 2 }}>
        {tree.length === 0 ? (
          <Typography color="text.secondary">
            No folders yet. Create one, or add transactions to a folder from the Transactions tab.
          </Typography>
        ) : (
          <SimpleTreeView defaultExpandedItems={expanded}>{renderTree(tree)}</SimpleTreeView>
        )}
      </Paper>

      {/* Editor */}
      <Dialog open={editorOpen} onClose={() => setEditorOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{editing ? "Edit folder" : "New folder"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} fullWidth />
            <TextField
              select
              label="Parent folder"
              value={form.parent ?? ""}
              onChange={(e) => setForm({ ...form, parent: e.target.value === "" ? null : Number(e.target.value) })}
              fullWidth
            >
              <MenuItem value="">
                <em>None (root)</em>
              </MenuItem>
              {flat
                .filter((f) => !editing || f.id !== editing.id)
                .map((f) => (
                  <MenuItem key={f.id} value={f.id}>
                    {"\u00a0".repeat(f.depth * 2)}
                    {f.name}
                  </MenuItem>
                ))}
            </TextField>

            <Divider textAlign="left">
              <Typography variant="caption" color="text.secondary">
                Smart criteria (auto-include matching transactions)
              </Typography>
            </Divider>
            <Stack direction="row" spacing={2}>
              <Box sx={{ flexGrow: 1 }}>
                <TagMultiSelect tags={tags} value={form.tags} onChange={(v) => setForm({ ...form, tags: v })} label="Include tags" />
              </Box>
              <TextField
                select
                size="small"
                label="Match"
                value={form.tag_match}
                onChange={(e) => setForm({ ...form, tag_match: e.target.value })}
                sx={{ width: 110 }}
              >
                <MenuItem value="any">Any</MenuItem>
                <MenuItem value="all">All</MenuItem>
              </TextField>
            </Stack>
            <CriteriaFields value={form.criteria} onChange={(criteria) => setForm({ ...form, criteria })} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditorOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={save} disabled={!form.name.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {/* Transactions view */}
      <Dialog open={Boolean(viewFolder)} onClose={() => setViewFolder(null)} fullWidth maxWidth="lg">
        <DialogTitle>{viewFolder?.name} — transactions</DialogTitle>
        <DialogContent>
          <Box sx={{ mb: 1, minHeight: 36 }}>
            {viewSelection.length > 0 && (
              <Button size="small" color="error" startIcon={<DeleteIcon />} onClick={removeFromFolder}>
                Exclude {viewSelection.length} from folder
              </Button>
            )}
          </Box>
          <DataGrid
            autoHeight
            rows={viewRows}
            loading={viewLoading}
            columns={[
              { field: "operation_date", headerName: "Date", width: 120 },
              { field: "concept", headerName: "Concept", flex: 1, minWidth: 280 },
              { field: "counterparty", headerName: "Counterparty", width: 180 },
              {
                field: "amount",
                headerName: "Amount",
                width: 140,
                type: "number",
                valueFormatter: (value, row) => currency(value, row.currency),
              },
            ]}
            checkboxSelection
            rowSelectionModel={viewSelection}
            onRowSelectionModelChange={setViewSelection}
            disableRowSelectionOnClick
            pageSizeOptions={[25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
          />
        </DialogContent>
        <DialogActions>
          <Button startIcon={<DownloadIcon />} onClick={() => exportFolder(viewFolder)}>
            Export
          </Button>
          <Button onClick={() => setViewFolder(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function Actions({ onAction, onAddChild, onView, onEdit, onExport, onDelete }) {
  return (
    <Stack direction="row" spacing={0.5}>
      <Tooltip title="View transactions">
        <IconButton size="small" onClick={onAction(onView)}>
          <ListIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Add subfolder">
        <IconButton size="small" onClick={onAction(onAddChild)}>
          <AddIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Edit">
        <IconButton size="small" onClick={onAction(onEdit)}>
          <EditIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Export .xlsx">
        <IconButton size="small" onClick={onAction(onExport)}>
          <DownloadIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Delete">
        <IconButton size="small" color="error" onClick={onAction(onDelete)}>
          <DeleteIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Stack>
  );
}
