import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import LinkOffIcon from "@mui/icons-material/LinkOff";
import { DataGrid } from "@mui/x-data-grid";
import api from "../api";
import RecurrenceDialog, { CATS, FREQS, WEEKDAYS } from "../components/RecurrenceDialog";

import { money as currency } from "../money";

const STATUS_COLOR = {
  paid: "success",
  upcoming: "info",
  overdue: "warning",
};

const monthLabel = (iso) => {
  if (!iso) return "";
  const [y, m] = iso.split("-");
  const d = new Date(Number(y), Number(m) - 1, 1);
  return d.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
};

function Kpi({ label, value, color, hint }) {
  return (
    <Paper variant="outlined" sx={{ px: 3, py: 1.5, flex: 1, minWidth: 150 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" sx={{ color, fontWeight: 700 }}>
        {value}
      </Typography>
      {hint && (
        <Typography variant="caption" color="text.secondary">
          {hint}
        </Typography>
      )}
    </Paper>
  );
}

export default function Recurring() {
  const [rows, setRows] = useState([]);
  const [forecast, setForecast] = useState(null);
  const [tags, setTags] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [detail, setDetail] = useState(null);
  const [members, setMembers] = useState([]);
  const [suggested, setSuggested] = useState([]);

  const load = async () => {
    const [r, f, t, a] = await Promise.all([
      api.get("/recurrences/", { params: { page_size: 200 } }),
      api.get("/recurrences/forecast/"),
      api.get("/tags/", { params: { page_size: 200 } }),
      api.get("/accounts/", { params: { page_size: 200 } }),
    ]);
    setRows(r.data.results);
    setForecast(f.data);
    setTags(t.data.results);
    setAccounts(a.data.results);
  };

  useEffect(() => {
    load();
  }, []);

  const openNew = () => {
    setEditing(null);
    setOpen(true);
  };

  const openEdit = (row) => {
    setEditing(row);
    setOpen(true);
  };

  const remove = async (row) => {
    await api.delete(`/recurrences/${row.id}/`);
    if (detail?.id === row.id) setDetail(null);
    load();
  };

  const openDetail = async (row) => {
    setDetail(row);
    const [mem, sug] = await Promise.all([
      api.get(`/recurrences/${row.id}/transactions/`, { params: { page_size: 100 } }),
      api.get(`/recurrences/${row.id}/suggest/`),
    ]);
    setMembers(mem.data.results || mem.data);
    setSuggested(sug.data);
  };

  const attach = async (ids, detach = false) => {
    if (!detail) return;
    const { data } = await api.post(`/recurrences/${detail.id}/attach/`, {
      transaction_ids: ids,
      detach,
    });
    setDetail(data.recurrence);
    await openDetail(data.recurrence);
    load();
  };

  const dueLabel = (row) => {
    if (row.frequency === "week") return WEEKDAYS[row.due_day] || row.due_day;
    return `day ${row.due_day}`;
  };

  const columns = [
      {
        field: "name",
        headerName: "Name",
        flex: 1,
        minWidth: 180,
        renderCell: (p) => (
          <Button
            size="small"
            onClick={() => openDetail(p.row)}
            sx={{ textTransform: "none", fontWeight: 600, justifyContent: "flex-start" }}
          >
            {p.value}
          </Button>
        ),
      },
      {
        field: "category",
        headerName: "Category",
        width: 130,
        valueGetter: (value) => CATS.find((c) => c.value === value)?.label || value,
      },
      {
        field: "frequency",
        headerName: "Cadence",
        width: 150,
        valueGetter: (_, row) =>
          `${FREQS.find((f) => f.value === row.frequency)?.label || row.frequency} · ${dueLabel(row)}`,
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
        field: "status",
        headerName: "Status",
        width: 120,
        renderCell: (p) => (
          <Stack direction="row" spacing={0.5} alignItems="center">
            <Chip size="small" label={p.value} color={STATUS_COLOR[p.value] || "default"} />
            {!p.row.is_active && <Chip size="small" label="off" />}
          </Stack>
        ),
      },
      { field: "next_due", headerName: "Next due", width: 120 },
      { field: "last_date", headerName: "Last paid", width: 120 },
      {
        field: "occurrence_count",
        headerName: "Tx",
        width: 70,
        type: "number",
      },
      {
        field: "next_month_remaining_eur",
        headerName: "Next month (EUR)",
        width: 160,
        type: "number",
        renderCell: (p) => {
          const eur = p.value;
          const native = p.row.next_month_remaining;
          if (!p.row.next_month_count) {
            return <Typography variant="body2" color="text.secondary">—</Typography>;
          }
          return (
            <Typography
              variant="body2"
              sx={{ color: (eur ?? native) < 0 ? "error.main" : "success.main", fontWeight: 600 }}
            >
              {eur == null ? currency(native, p.row.currency) : currency(eur)}
              {p.row.next_month_count > 1 ? ` ×${p.row.next_month_count}` : ""}
            </Typography>
          );
        },
      },
      {
        field: "actions",
        headerName: "",
        width: 100,
        sortable: false,
        filterable: false,
        renderCell: (p) => (
          <Stack direction="row">
            <IconButton size="small" onClick={() => openEdit(p.row)}>
              <EditIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" color="error" onClick={() => remove(p.row)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Stack>
        ),
      },
    ];

  const next = forecast?.next_month;
  const rest = forecast?.this_month;
  const leftoverHint = forecast?.converted
    ? "Converted to EUR"
    : forecast?.missing_fx
      ? "Some amounts skipped (no FX rate)"
      : "EUR";
  const leftoverRows = [
    ...(forecast?.accounts || []),
    ...(forecast?.unassigned?.this_month?.count || forecast?.unassigned?.next_month?.count
      ? [
          {
            id: "unassigned",
            name: "No account",
            effective_eur: null,
            this_month: forecast.unassigned.this_month,
            next_month: forecast.unassigned.next_month,
          },
        ]
      : []),
  ];
  const leftoverColor = (v) =>
    v == null ? "text.secondary" : v < 0 ? "error.main" : v > 0 ? "success.main" : "text.secondary";

  return (
    <Box>
      <Stack direction="row" justifyContent="flex-end" sx={{ mb: 2 }}>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          New recurrence
        </Button>
      </Stack>

      {forecast && (
        <>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Remaining this month ({monthLabel(rest?.start)})
          </Typography>
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", mb: 2 }} useFlexGap>
            <Kpi label="Still in" value={currency(rest?.income)} color="success.main" />
            <Kpi label="Still out" value={currency(rest?.expense)} color="error.main" />
            <Kpi label="Net" value={currency(rest?.net)} />
          </Stack>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Next month remaining ({monthLabel(next?.start)})
          </Typography>
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", mb: 2 }} useFlexGap>
            <Kpi label="Income" value={currency(next?.income)} color="success.main" />
            <Kpi label="Expenses" value={currency(next?.expense)} color="error.main" />
            <Kpi label="Net" value={currency(next?.net)} hint={leftoverHint} />
          </Stack>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Leftover balance (EUR)
          </Typography>
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", mb: 2 }} useFlexGap>
            <Kpi
              label="Now"
              value={currency(forecast.current_eur)}
              color={leftoverColor(forecast.current_eur)}
            />
            <Kpi
              label={`End of ${monthLabel(rest?.start)}`}
              value={currency(rest?.leftover_eur)}
              color={leftoverColor(rest?.leftover_eur)}
            />
            <Kpi
              label={`End of ${monthLabel(next?.start)}`}
              value={currency(next?.leftover_eur)}
              color={leftoverColor(next?.leftover_eur)}
              hint={leftoverHint}
            />
          </Stack>
          {leftoverRows.length > 0 && (
            <Paper variant="outlined" sx={{ mb: 2 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Account</TableCell>
                    <TableCell align="right">Now</TableCell>
                    <TableCell align="right">This month</TableCell>
                    <TableCell align="right">Next month</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {leftoverRows.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {row.name}
                        </Typography>
                        {row.credit_limit ? (
                          <Typography variant="caption" color="text.secondary">
                            Credit · available {currency(row.balance, row.currency)} of{" "}
                            {currency(row.credit_limit, row.currency)}
                          </Typography>
                        ) : row.currency && row.currency !== "EUR" && row.effective != null ? (
                          <Typography variant="caption" color="text.secondary">
                            {currency(row.effective, row.currency)}
                          </Typography>
                        ) : null}
                      </TableCell>
                      <TableCell align="right" sx={{ color: leftoverColor(row.effective_eur), fontWeight: 600 }}>
                        {row.effective_eur == null ? "—" : currency(row.effective_eur)}
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: leftoverColor(row.this_month?.leftover_eur), fontWeight: 600 }}
                      >
                        {currency(row.this_month?.leftover_eur)}
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: leftoverColor(row.next_month?.leftover_eur), fontWeight: 600 }}
                      >
                        {currency(row.next_month?.leftover_eur)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Paper>
          )}
        </>
      )}

      <DataGrid
        autoHeight
        rows={rows}
        columns={columns}
        pageSizeOptions={[25, 50, 100]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        disableRowSelectionOnClick
        sx={{ bgcolor: "background.paper", "& .MuiDataGrid-cell": { py: 0.5 } }}
      />
      {rows.length === 0 && (
        <Typography color="text.secondary" sx={{ mt: 2 }}>
          No recurrences yet. Create one here or pick a transaction and choose Make
          recurring.
        </Typography>
      )}

      <RecurrenceDialog
        open={open}
        recurrence={editing}
        tags={tags}
        accounts={accounts}
        onClose={() => setOpen(false)}
        onSaved={() => load()}
      />

      <Dialog
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>{detail?.name}</DialogTitle>
        <DialogContent>
          {detail && (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip size="small" label={detail.status} color={STATUS_COLOR[detail.status]} />
                <Chip size="small" variant="outlined" label={`${detail.occurrence_count} attached`} />
                <Button
                  size="small"
                  component={RouterLink}
                  to={`/transactions?recurrence=${detail.id}`}
                >
                  View in transactions
                </Button>
              </Stack>
              <Typography variant="subtitle2">Attached</Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Date</TableCell>
                    <TableCell>Concept</TableCell>
                    <TableCell align="right">Amount</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {members.map((tx) => (
                    <TableRow key={tx.id}>
                      <TableCell>{tx.operation_date}</TableCell>
                      <TableCell>{tx.counterparty || tx.concept}</TableCell>
                      <TableCell align="right">{currency(tx.amount, tx.currency)}</TableCell>
                      <TableCell align="right">
                        <IconButton size="small" onClick={() => attach([tx.id], true)}>
                          <LinkOffIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                  {members.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={4}>
                        <Typography variant="body2" color="text.secondary">
                          No transactions attached yet.
                        </Typography>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
              {suggested.length > 0 && (
                <>
                  <Typography variant="subtitle2">Suggested historical matches</Typography>
                  <Table size="small">
                    <TableBody>
                      {suggested.map((tx) => (
                        <TableRow key={tx.id}>
                          <TableCell>{tx.operation_date}</TableCell>
                          <TableCell>{tx.counterparty || tx.concept}</TableCell>
                          <TableCell align="right">
                            {currency(tx.amount, tx.currency)}
                          </TableCell>
                          <TableCell align="right">
                            <Button size="small" onClick={() => attach([tx.id])}>
                              Attach
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <Button
                    size="small"
                    onClick={() => attach(suggested.map((t) => t.id))}
                  >
                    Attach all suggested
                  </Button>
                </>
              )}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetail(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
