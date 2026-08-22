import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import CreateNewFolderIcon from "@mui/icons-material/CreateNewFolder";
import LocalOfferIcon from "@mui/icons-material/LocalOffer";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import RepeatIcon from "@mui/icons-material/Repeat";
import { DataGrid } from "@mui/x-data-grid";
import api from "../api";
import TagMultiSelect from "../components/TagMultiSelect";
import { TagCell, TagEditorPopover } from "../components/TagCell";
import ReceiptDialog from "../components/ReceiptDialog";
import RecurrenceDialog from "../components/RecurrenceDialog";

const currency = (v, code) =>
  new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: code || "EUR",
  }).format(v);

const QUARTERS = [
  { value: "", label: "Any quarter" },
  { value: "this", label: "This quarter" },
  { value: "prev", label: "Previous quarter" },
  { value: "Q1", label: "Q1" },
  { value: "Q2", label: "Q2" },
  { value: "Q3", label: "Q3" },
  { value: "Q4", label: "Q4" },
];

export default function Transactions() {
  const [searchParams] = useSearchParams();
  const [rows, setRows] = useState([]);
  const [rowCount, setRowCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [paginationModel, setPaginationModel] = useState({ page: 0, pageSize: 50 });
  const [sortModel, setSortModel] = useState([{ field: "operation_date", sort: "desc" }]);

  const [kind, setKind] = useState("all");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [counterparty, setCounterparty] = useState("");
  const [debouncedCounterparty, setDebouncedCounterparty] = useState("");
  const [dateFrom, setDateFrom] = useState(() => searchParams.get("date_from") || "");
  const [dateTo, setDateTo] = useState(() => searchParams.get("date_to") || "");
  const [quarter, setQuarter] = useState("");
  const [year, setYear] = useState("");
  const [tagFilter, setTagFilter] = useState(() => {
    const raw = searchParams.get("tags");
    if (!raw) return [];
    return raw.split(",").map(Number).filter(Boolean);
  });
  const [source, setSource] = useState("");
  const [untagged, setUntagged] = useState(false);
  const [accountFilter, setAccountFilter] = useState(
    () => searchParams.get("account") || "",
  );
  const [recurrenceFilter, setRecurrenceFilter] = useState(
    () => searchParams.get("recurrence") || "",
  );

  const [tags, setTags] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [summary, setSummary] = useState({
    income: 0,
    expense: 0,
    net: 0,
    count: 0,
    currency: "EUR",
    mixed: false,
    converted: false,
    currencies: [],
  });
  const [selection, setSelection] = useState([]);
  const [feedback, setFeedback] = useState(null);

  const [folderDialog, setFolderDialog] = useState(false);
  const [folders, setFolders] = useState([]);
  const [targetFolder, setTargetFolder] = useState("");
  const [newFolderName, setNewFolderName] = useState("");

  const [tagDialog, setTagDialog] = useState(false);
  const [tagsToAdd, setTagsToAdd] = useState([]);

  const [aiDialog, setAiDialog] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiSuggestions, setAiSuggestions] = useState([]);

  const [tagEditor, setTagEditor] = useState(null);
  const [receiptId, setReceiptId] = useState(null);
  const [recurDialog, setRecurDialog] = useState(false);
  const [recurForm, setRecurForm] = useState({
    name: "",
    frequency: "month",
    category: "other",
  });
  const [editingRec, setEditingRec] = useState(null);
  const [recurEditOpen, setRecurEditOpen] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedCounterparty(counterparty), 400);
    return () => clearTimeout(t);
  }, [counterparty]);

  const loadTags = useCallback(async () => {
    const { data } = await api.get("/tags/", { params: { page_size: 200 } });
    setTags(data.results);
  }, []);

  useEffect(() => {
    loadTags();
  }, [loadTags]);

  useEffect(() => {
    api
      .get("/accounts/", { params: { page_size: 200 } })
      .then(({ data }) => setAccounts(data.results));
  }, []);

  const params = useMemo(() => {
    const p = {
      page: paginationModel.page + 1,
      page_size: paginationModel.pageSize,
    };
    if (kind !== "all") p.kind = kind;
    if (debouncedSearch) p.search = debouncedSearch;
    if (debouncedCounterparty) p.counterparty = debouncedCounterparty;
    if (dateFrom) p.date_from = dateFrom;
    if (dateTo) p.date_to = dateTo;
    if (quarter) p.quarter = quarter;
    if (year) p.year = year;
    if (tagFilter.length) p.tags = tagFilter.join(",");
    if (source) p.source = source;
    if (untagged) p.untagged = "true";
    if (accountFilter) p.account = accountFilter;
    if (recurrenceFilter) p.recurrence = recurrenceFilter;
    if (sortModel.length) {
      p.ordering = sortModel
        .map((s) => (s.sort === "desc" ? "-" : "") + s.field)
        .join(",");
    }
    return p;
  }, [
    paginationModel,
    kind,
    debouncedSearch,
    debouncedCounterparty,
    dateFrom,
    dateTo,
    quarter,
    year,
    tagFilter,
    source,
    untagged,
    accountFilter,
    recurrenceFilter,
    sortModel,
  ]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, sum] = await Promise.all([
        api.get("/transactions/", { params }),
        api.get("/transactions/summary/", { params }),
      ]);
      setRows(list.data.results);
      setRowCount(list.data.count);
      setSummary(sum.data);
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    load();
  }, [load]);

  // Drop selection when filters change so actions never apply to hidden rows.
  useEffect(() => {
    setSelection([]);
  }, [
    kind,
    debouncedSearch,
    debouncedCounterparty,
    dateFrom,
    dateTo,
    quarter,
    year,
    tagFilter,
    source,
    untagged,
    accountFilter,
    recurrenceFilter,
  ]);

  const setRowTags = (txId, updater) =>
    setRows((rs) =>
      rs.map((r) => (r.id === txId ? { ...r, tags: updater(r.tags || []) } : r)),
    );

  const addTagToRow = async (row, tag) => {
    await api.post("/transactions/tag/", {
      transaction_ids: [row.id],
      add: [tag.id],
    });
    setRowTags(row.id, (cur) =>
      cur.some((t) => t.id === tag.id)
        ? cur
        : [...cur, { id: tag.id, name: tag.name, color: tag.color, source: "manual" }],
    );
  };

  const removeTagFromRow = async (row, tagId) => {
    await api.post("/transactions/tag/", {
      transaction_ids: [row.id],
      remove: [tagId],
    });
    setRowTags(row.id, (cur) => cur.filter((t) => t.id !== tagId));
  };

  const createAndAddTagToRow = async (row, name) => {
    const existing = tags.find((t) => t.name.toLowerCase() === name.toLowerCase());
    const tag = existing || (await api.post("/tags/", { name })).data;
    await addTagToRow(row, tag);
    if (!existing) loadTags();
  };

  const openRecurrence = async (id) => {
    const { data } = await api.get(`/recurrences/${id}/`);
    setEditingRec(data);
    setRecurEditOpen(true);
  };

  const columns = [
    {
      field: "operation_date",
      headerName: "Date",
      width: 148,
      renderCell: (p) => (
        <Stack direction="row" alignItems="center" spacing={0.25} sx={{ overflow: "hidden" }}>
          <span>{p.value}</span>
          {p.row.recurrence && (
            <IconButton
              size="small"
              title={p.row.recurrence_name || "Edit recurrence"}
              onClick={(e) => {
                e.stopPropagation();
                openRecurrence(p.row.recurrence);
              }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <RepeatIcon fontSize="small" color="primary" />
            </IconButton>
          )}
        </Stack>
      ),
    },
    {
      field: "concept",
      headerName: "Concept",
      flex: 1,
      minWidth: 260,
      renderCell: (p) => {
        const openReceipt = (e) => {
          e.stopPropagation();
          if (p.row.receipt_id) setReceiptId(p.row.receipt_id);
        };
        const stopRow = (e) => e.stopPropagation();
        return (
          <Stack direction="row" spacing={0.75} alignItems="center" sx={{ overflow: "hidden" }}>
            {p.row.receipt_id && (
              <Chip
                size="small"
                label={
                  p.row.receipt_kind === "invoice"
                    ? "Invoice"
                    : `(${p.row.item_count || 0} items)`
                }
                color="warning"
                variant="outlined"
                onClick={openReceipt}
                onMouseDown={stopRow}
              />
            )}
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{p.value}</span>
          </Stack>
        );
      },
    },
    { field: "counterparty", headerName: "Counterparty", width: 180 },
    {
      field: "account_label",
      headerName: "Account",
      width: 130,
      sortable: false,
      valueGetter: (value) => value || "—",
    },
    {
      field: "amount",
      headerName: "Amount",
      width: 130,
      type: "number",
      renderCell: (p) => (
        <Typography
          variant="body2"
          sx={{ color: p.value < 0 ? "error.main" : "success.main", fontWeight: 600 }}
        >
          {currency(p.value, p.row.currency)}
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
          onRemove={removeTagFromRow}
        />
      ),
    },
  ];

  const openFolderDialog = async () => {
    const { data } = await api.get("/folders/", { params: { page_size: 200 } });
    setFolders(data.results);
    setTargetFolder("");
    setNewFolderName("");
    setFolderDialog(true);
  };

  const addToFolder = async () => {
    let folderId = targetFolder;
    if (newFolderName.trim()) {
      const { data } = await api.post("/folders/", { name: newFolderName.trim() });
      folderId = data.id;
    }
    if (!folderId) return;
    const { data } = await api.post(`/folders/${folderId}/update-transactions/`, {
      add: selection,
    });
    setFolderDialog(false);
    setSelection([]);
    setFeedback(`Added ${selection.length} to folder (now ${data.transaction_count}).`);
  };

  const applyTags = async () => {
    await api.post("/transactions/tag/", {
      transaction_ids: selection,
      add: tagsToAdd,
    });
    setTagDialog(false);
    setTagsToAdd([]);
    setSelection([]);
    setFeedback("Tags applied.");
    load();
  };

  const runAi = async () => {
    setAiDialog(true);
    setAiLoading(true);
    setAiSuggestions([]);
    try {
      const body = selection.length
        ? { transaction_ids: selection }
        : { scope: "untagged", limit: 50 };
      const { data } = await api.post("/ai/classify/", body);
      setAiSuggestions(
        data.suggestions.map((s) => ({ ...s, accepted: true })),
      );
    } catch (err) {
      setFeedback(err.response?.data?.detail || "AI classification failed.");
      setAiDialog(false);
    } finally {
      setAiLoading(false);
    }
  };

  const applyAi = async () => {
    const items = aiSuggestions
      .filter((s) => s.accepted && (s.tag_ids.length || s.new_tags.length))
      .map((s) => ({
        transaction_id: s.transaction_id,
        tag_ids: s.tag_ids,
        new_tags: s.new_tags,
        confidence: s.confidence,
      }));
    if (items.length) {
      const { data } = await api.post("/ai/apply/", { items });
      setFeedback(
        `AI applied: ${data.assignments_created} tag(s), ${data.new_tags_created} new tag(s) created.`,
      );
    }
    setAiDialog(false);
    setSelection([]);
    loadTags();
    load();
  };

  return (
    <Box>
      <SummaryCards summary={summary} />

      <Paper variant="outlined" sx={{ p: 2, my: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
            <ToggleButtonGroup size="small" exclusive value={kind} onChange={(_, v) => v && setKind(v)}>
              <ToggleButton value="all">All</ToggleButton>
              <ToggleButton value="income">Income</ToggleButton>
              <ToggleButton value="expense">Expenses</ToggleButton>
            </ToggleButtonGroup>
            <TextField
              select
              size="small"
              label="Account"
              value={accountFilter}
              onChange={(e) => setAccountFilter(e.target.value)}
              sx={{ minWidth: 160 }}
            >
              <MenuItem value="">All accounts</MenuItem>
              {accounts.map((a) => (
                <MenuItem key={a.id} value={a.id}>
                  {a.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label="Quarter"
              value={quarter}
              onChange={(e) => setQuarter(e.target.value)}
              sx={{ minWidth: 150 }}
            >
              {QUARTERS.map((q) => (
                <MenuItem key={q.value} value={q.value}>
                  {q.label}
                </MenuItem>
              ))}
            </TextField>
            {["Q1", "Q2", "Q3", "Q4"].includes(quarter) && (
              <TextField
                size="small"
                label="Year"
                type="number"
                value={year}
                onChange={(e) => setYear(e.target.value)}
                sx={{ width: 110 }}
              />
            )}
            <TextField
              size="small"
              label="Search concept"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              sx={{ minWidth: 180 }}
            />
            <TextField
              size="small"
              label="Counterparty"
              value={counterparty}
              onChange={(e) => setCounterparty(e.target.value)}
              sx={{ minWidth: 160 }}
            />
          </Stack>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
            <Box sx={{ minWidth: 220 }}>
              <TagMultiSelect tags={tags} value={tagFilter} onChange={setTagFilter} label="Filter by tags" />
            </Box>
            <TextField
              select
              size="small"
              label="Tag source"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              sx={{ minWidth: 140 }}
            >
              <MenuItem value="">Any</MenuItem>
              <MenuItem value="manual">Manual</MenuItem>
              <MenuItem value="rule">Rule</MenuItem>
              <MenuItem value="ai">AI</MenuItem>
              <MenuItem value="schedule">Schedule</MenuItem>
            </TextField>
            <FormControlLabel
              control={<Switch checked={untagged} onChange={(e) => setUntagged(e.target.checked)} />}
              label="Untagged only"
            />
            <TextField size="small" label="From" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }} />
            <TextField size="small" label="To" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }} />
          </Stack>
          <Divider />
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="body2" color="text.secondary">
              {selection.length} selected
            </Typography>
            <Box sx={{ flexGrow: 1 }} />
            <Button startIcon={<LocalOfferIcon />} disabled={!selection.length} onClick={() => setTagDialog(true)}>
              Tag
            </Button>
            <Button startIcon={<CreateNewFolderIcon />} disabled={!selection.length} onClick={openFolderDialog}>
              Add to folder
            </Button>
            <Button
              startIcon={<RepeatIcon />}
              disabled={selection.length !== 1}
              onClick={() => {
                const row = rows.find((r) => r.id === selection[0]);
                setRecurForm({
                  name: (row?.counterparty || row?.concept || "Recurring").slice(0, 120),
                  frequency: "month",
                  category: "other",
                });
                setRecurDialog(true);
              }}
            >
              Make recurring
            </Button>
            <Button variant="contained" startIcon={<AutoAwesomeIcon />} onClick={runAi}>
              {selection.length ? `AI classify (${selection.length})` : "AI classify untagged"}
            </Button>
          </Stack>
        </Stack>
      </Paper>

      {feedback && (
        <Alert severity="info" sx={{ mb: 2 }} onClose={() => setFeedback(null)}>
          {feedback}
        </Alert>
      )}

      <div style={{ width: "100%" }}>
        <DataGrid
          autoHeight
          rows={rows}
          columns={columns}
          loading={loading}
          checkboxSelection
          rowSelectionModel={selection}
          onRowSelectionModelChange={setSelection}
          paginationMode="server"
          rowCount={rowCount}
          paginationModel={paginationModel}
          onPaginationModelChange={setPaginationModel}
          pageSizeOptions={[25, 50, 100]}
          sortingMode="server"
          sortModel={sortModel}
          onSortModelChange={setSortModel}
          getRowHeight={() => "auto"}
          disableRowSelectionOnClick
          sx={{ bgcolor: "background.paper", "& .MuiDataGrid-cell": { py: 0.5 } }}
        />
      </div>

      <TagEditorPopover
        anchorEl={tagEditor?.anchorEl}
        row={rows.find((r) => r.id === tagEditor?.rowId)}
        allTags={tags}
        onClose={() => setTagEditor(null)}
        onAddExisting={addTagToRow}
        onCreateAndAdd={createAndAddTagToRow}
      />

      <ReceiptDialog
        receiptId={receiptId}
        allTags={tags}
        onClose={() => setReceiptId(null)}
        onSaved={load}
        onTagsChanged={loadTags}
      />

      {/* Add to folder */}
      <Dialog open={folderDialog} onClose={() => setFolderDialog(false)} fullWidth maxWidth="xs">
        <DialogTitle>Add {selection.length} to a folder</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              select
              label="Existing folder"
              value={targetFolder}
              onChange={(e) => setTargetFolder(e.target.value)}
              disabled={Boolean(newFolderName.trim())}
              fullWidth
            >
              <MenuItem value="">
                <em>None</em>
              </MenuItem>
              {folders.map((f) => (
                <MenuItem key={f.id} value={f.id}>
                  {f.name} ({f.transaction_count})
                </MenuItem>
              ))}
            </TextField>
            <Typography variant="body2" color="text.secondary" align="center">
              — or —
            </Typography>
            <TextField label="New folder name" value={newFolderName} onChange={(e) => setNewFolderName(e.target.value)} fullWidth />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFolderDialog(false)}>Cancel</Button>
          <Button variant="contained" onClick={addToFolder} disabled={!targetFolder && !newFolderName.trim()}>
            Add
          </Button>
        </DialogActions>
      </Dialog>

      {/* Bulk tag */}
      <Dialog open={tagDialog} onClose={() => setTagDialog(false)} fullWidth maxWidth="xs">
        <DialogTitle>Tag {selection.length} transaction(s)</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 1 }}>
            <TagMultiSelect tags={tags} value={tagsToAdd} onChange={setTagsToAdd} label="Tags to add" />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTagDialog(false)}>Cancel</Button>
          <Button variant="contained" onClick={applyTags} disabled={!tagsToAdd.length}>
            Apply
          </Button>
        </DialogActions>
      </Dialog>

      {/* AI review */}
      <Dialog open={aiDialog} onClose={() => setAiDialog(false)} fullWidth maxWidth="md">
        <DialogTitle>AI tag suggestions</DialogTitle>
        <DialogContent dividers>
          {aiLoading ? (
            <Typography>Classifying…</Typography>
          ) : aiSuggestions.length === 0 ? (
            <Typography color="text.secondary">No suggestions.</Typography>
          ) : (
            <Stack spacing={1}>
              {aiSuggestions.map((s, i) => (
                <Paper key={s.transaction_id} variant="outlined" sx={{ p: 1.5 }}>
                  <Stack direction="row" spacing={2} alignItems="center">
                    <Switch
                      checked={s.accepted}
                      onChange={(e) => {
                        const next = [...aiSuggestions];
                        next[i] = { ...s, accepted: e.target.checked };
                        setAiSuggestions(next);
                      }}
                    />
                    <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                      <Typography variant="body2" noWrap>
                        {s.counterparty || s.concept}
                      </Typography>
                      <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: "wrap" }}>
                        {s.tag_names.map((n) => (
                          <Chip key={n} size="small" label={n} color="primary" />
                        ))}
                        {s.new_tags.map((n) => (
                          <Chip key={n} size="small" label={`+ ${n}`} color="success" variant="outlined" />
                        ))}
                        {s.tag_names.length === 0 && s.new_tags.length === 0 && (
                          <Typography variant="caption" color="text.secondary">
                            no suggestion
                          </Typography>
                        )}
                      </Stack>
                    </Box>
                    <Typography variant="caption" color="text.secondary">
                      {s.confidence != null ? `${Math.round(s.confidence * 100)}%` : ""}
                    </Typography>
                  </Stack>
                </Paper>
              ))}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAiDialog(false)}>Cancel</Button>
          <Button variant="contained" onClick={applyAi} disabled={aiLoading || !aiSuggestions.some((s) => s.accepted)}>
            Apply accepted
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={recurDialog} onClose={() => setRecurDialog(false)} fullWidth maxWidth="xs">
        <DialogTitle>Make recurring</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Name"
              value={recurForm.name}
              onChange={(e) => setRecurForm({ ...recurForm, name: e.target.value })}
              fullWidth
            />
            <TextField
              select
              label="Frequency"
              value={recurForm.frequency}
              onChange={(e) => setRecurForm({ ...recurForm, frequency: e.target.value })}
            >
              <MenuItem value="week">Weekly</MenuItem>
              <MenuItem value="month">Monthly</MenuItem>
              <MenuItem value="quarter">Quarterly</MenuItem>
              <MenuItem value="year">Yearly</MenuItem>
            </TextField>
            <TextField
              select
              label="Category"
              value={recurForm.category}
              onChange={(e) => setRecurForm({ ...recurForm, category: e.target.value })}
            >
              <MenuItem value="subscription">Subscription</MenuItem>
              <MenuItem value="loan">Loan</MenuItem>
              <MenuItem value="tax">Tax</MenuItem>
              <MenuItem value="income">Income</MenuItem>
              <MenuItem value="other">Other</MenuItem>
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRecurDialog(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!recurForm.name.trim() || selection.length !== 1}
            onClick={async () => {
              const { data } = await api.post("/recurrences/from_transaction/", {
                transaction_id: selection[0],
                name: recurForm.name,
                frequency: recurForm.frequency,
                category: recurForm.category,
              });
              setRecurDialog(false);
              setSelection([]);
              setEditingRec(data);
              setRecurEditOpen(true);
              load();
            }}
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <RecurrenceDialog
        open={recurEditOpen}
        recurrence={editingRec}
        tags={tags}
        accounts={accounts}
        onClose={() => setRecurEditOpen(false)}
        onSaved={() => load()}
      />
    </Box>
  );
}

function SummaryCards({ summary }) {
  const code = summary.currency || "EUR";
  const item = (label, value, color) => (
    <Paper variant="outlined" sx={{ px: 3, py: 1.5, flex: 1, minWidth: 160 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" sx={{ color, fontWeight: 700 }}>
        {value == null ? "—" : currency(value, code)}
      </Typography>
    </Paper>
  );
  return (
    <Stack spacing={1} sx={{ width: "100%" }}>
      {summary.converted && (
        <Alert severity="info">
          Totals in EUR using NBU daily rates
          {summary.currencies?.length
            ? ` · native ${summary.currencies.map((c) => c.currency || c).join(", ")}`
            : ""}
          .
        </Alert>
      )}
      {summary.mixed && !summary.converted && summary.income == null && (
        <Alert severity="warning">
          Mixed currencies
          {summary.currencies?.length
            ? ` (${summary.currencies.map((c) => c.currency || c).join(", ")})`
            : ""}
          — rates were unavailable, so totals are hidden.
        </Alert>
      )}
      <Stack direction="row" spacing={2} sx={{ width: "100%" }}>
        {item("Income", summary.income, "success.main")}
        {item("Expenses", summary.expense, "error.main")}
        {item("Net", summary.net, "text.primary")}
        <Paper variant="outlined" sx={{ px: 3, py: 1.5, flex: 1, minWidth: 120 }}>
          <Typography variant="caption" color="text.secondary">
            Count
          </Typography>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {summary.count || 0}
          </Typography>
        </Paper>
      </Stack>
    </Stack>
  );
}
