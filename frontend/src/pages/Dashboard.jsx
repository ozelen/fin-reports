import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { PieChart } from "@mui/x-charts/PieChart";
import { BarChart } from "@mui/x-charts/BarChart";
import { LineChart } from "@mui/x-charts/LineChart";
import api from "../api";
import { money as currency } from "../money";

const QUARTERS = [
  { value: "", label: "All time" },
  { value: "this", label: "This quarter" },
  { value: "prev", label: "Previous quarter" },
  { value: "Q1", label: "Q1" },
  { value: "Q2", label: "Q2" },
  { value: "Q3", label: "Q3" },
  { value: "Q4", label: "Q4" },
];

const UNTAGGED_COLOR = "#9e9e9e";
const OTHER_COLOR = "#c7c7c7";

const GRANULARITIES = [
  { value: "day", label: "Daily" },
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
  { value: "quarter", label: "Quarterly" },
  { value: "year", label: "Yearly" },
];

const POS_COLOR = "#2e9e5b";
const NEG_COLOR = "#e04352";

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 8 }, (_, i) => CURRENT_YEAR - i);

export default function Dashboard() {
  const [quarter, setQuarter] = useState("");
  const [year, setYear] = useState("");
  const [account, setAccount] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [granularity, setGranularity] = useState("day");
  const [accounts, setAccounts] = useState([]);
  const [data, setData] = useState({
    tags: [],
    untagged: null,
    totals: null,
    mixed: false,
    converted: false,
    currencies: [],
  });
  const [series, setSeries] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api
      .get("/accounts/", { params: { page_size: 200 } })
      .then(({ data }) => setAccounts(data.results));
  }, []);

  const params = useMemo(() => {
    const p = {};
    if (quarter) p.quarter = quarter;
    if (year) p.year = year;
    if (account) p.account = account;
    if (dateFrom) p.date_from = dateFrom;
    if (dateTo) p.date_to = dateTo;
    return p;
  }, [quarter, year, account, dateFrom, dateTo]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [byTag, overTime] = await Promise.all([
        api.get("/transactions/by_tag/", { params }),
        api.get("/transactions/over_time/", {
          params: { ...params, granularity },
        }),
      ]);
      setData(byTag.data);
      setSeries(overTime.data.series);
    } finally {
      setLoading(false);
    }
  }, [params, granularity]);

  useEffect(() => {
    load();
  }, [load]);

  const { tags, untagged, totals, mixed, converted, currencies: dataCurrencies } = data;
  const moneyCode = totals?.currency || "EUR";

  const timeline = useMemo(() => {
    let running = 0;
    const dates = [];
    const pnl = [];
    for (const s of series) {
      running += s.net;
      dates.push(new Date(s.period));
      pnl.push(Math.round(running * 100) / 100);
    }
    return { dates, pnl };
  }, [series]);

  const expensePie = useMemo(
    () => buildPie(tags, untagged, "expense"),
    [tags, untagged],
  );
  const incomePie = useMemo(
    () => buildPie(tags, untagged, "income"),
    [tags, untagged],
  );

  const netBars = useMemo(() => {
    const top = [...tags]
      .filter((t) => t.income || t.expense)
      .sort((a, b) => Math.abs(b.net) - Math.abs(a.net))
      .slice(0, 12)
      .reverse();
    return {
      labels: top.map((t) => t.name),
      income: top.map((t) => t.income),
      expense: top.map((t) => t.expense),
    };
  }, [tags]);

  const coverage =
    totals && totals.count
      ? Math.round(((totals.count - (untagged?.count || 0)) / totals.count) * 100)
      : 0;

  const hasData = totals && totals.count > 0;

  return (
    <Box>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={2}
        alignItems={{ sm: "center" }}
        justifyContent="space-between"
        sx={{ mb: 2 }}
      >
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Dashboard
        </Typography>
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
          {accounts.length > 0 && (
            <TextField
              select
              size="small"
              label="Account"
              value={account}
              onChange={(e) => setAccount(e.target.value)}
              sx={{ minWidth: 150 }}
            >
              <MenuItem value="">All accounts</MenuItem>
              {accounts.map((a) => (
                <MenuItem key={a.id} value={a.id}>
                  {a.name}
                </MenuItem>
              ))}
            </TextField>
          )}
          <TextField
            select
            size="small"
            label="Period"
            value={quarter}
            onChange={(e) => setQuarter(e.target.value)}
            sx={{ minWidth: 160 }}
          >
            {QUARTERS.map((q) => (
              <MenuItem key={q.value} value={q.value}>
                {q.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Year"
            value={year}
            onChange={(e) => setYear(e.target.value)}
            sx={{ minWidth: 110 }}
          >
            <MenuItem value="">All years</MenuItem>
            {YEARS.map((y) => (
              <MenuItem key={y} value={y}>
                {y}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            size="small"
            label="From"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ width: 160 }}
          />
          <TextField
            size="small"
            label="To"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ width: 160 }}
          />
        </Stack>
      </Stack>

      {converted && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Totals in EUR using NBU daily rates
          {(dataCurrencies || []).length
            ? ` · native ${(dataCurrencies || []).join(", ")}`
            : ""}
          .
        </Alert>
      )}
      {mixed && !converted && totals?.income == null && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Mixed currencies ({(dataCurrencies || []).join(", ")}) — rates were
          unavailable, so totals are hidden.
        </Alert>
      )}

      <ChartCard
        title="Running PnL over time"
        empty={timeline.dates.length === 0}
        action={
          <TextField
            select
            size="small"
            value={granularity}
            onChange={(e) => setGranularity(e.target.value)}
            sx={{ minWidth: 130 }}
          >
            {GRANULARITIES.map((g) => (
              <MenuItem key={g.value} value={g.value}>
                {g.label}
              </MenuItem>
            ))}
          </TextField>
        }
      >
        <LineChart
          height={320}
          xAxis={[
            {
              scaleType: "time",
              data: timeline.dates,
              valueFormatter: (d) => formatDate(d, granularity),
            },
          ]}
          yAxis={[
            {
              valueFormatter: (v) => compactCurrency(v),
              colorMap: {
                type: "piecewise",
                thresholds: [0],
                colors: [NEG_COLOR, POS_COLOR],
              },
            },
          ]}
          series={[
            {
              data: timeline.pnl,
              label: "Running PnL",
              area: true,
              curve: "monotoneX",
              valueFormatter: (v) => (v == null ? "" : currency(v, moneyCode)),
              showMark: timeline.dates.length <= 60,
            },
          ]}
          margin={{ left: 64, right: 20, top: 20, bottom: 30 }}
          grid={{ horizontal: true }}
          slotProps={{ legend: { hidden: true } }}
          sx={{ "& .MuiAreaElement-root": { fillOpacity: 0.18 } }}
        />
      </ChartCard>
      <Box sx={{ mb: 2 }} />

      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", mb: 2 }} useFlexGap>
        <Kpi
          label="Income"
          value={totals?.income == null ? "—" : currency(totals.income, moneyCode)}
          color="success.main"
        />
        <Kpi
          label="Expenses"
          value={totals?.expense == null ? "—" : currency(totals.expense, moneyCode)}
          color="error.main"
        />
        <Kpi
          label="Net"
          value={totals?.net == null ? "—" : currency(totals.net, moneyCode)}
          color="text.primary"
        />
        <Kpi label="Transactions" value={totals?.count ?? 0} />
        <Kpi label="Tagged" value={`${coverage}%`} />
      </Stack>

      {!hasData && (
        <Paper variant="outlined" sx={{ p: 6, textAlign: "center" }}>
          <Typography color="text.secondary">
            {loading ? "Loading…" : "No transactions for this period."}
          </Typography>
        </Paper>
      )}

      {hasData && (
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
            <ChartCard title="Expenses by tag" empty={expensePie.length === 0}>
              <PieChart
                series={[
                  {
                    data: expensePie,
                    innerRadius: 55,
                    paddingAngle: 1,
                    cornerRadius: 3,
                    valueFormatter: (v) => currency(v.value, moneyCode),
                    highlightScope: { faded: "global", highlighted: "item" },
                  },
                ]}
                height={280}
                margin={{ top: 10, bottom: 10, left: 10, right: 10 }}
                slotProps={{ legend: { hidden: true } }}
              />
            </ChartCard>
            <ChartCard title="Income by tag" empty={incomePie.length === 0}>
              <PieChart
                series={[
                  {
                    data: incomePie,
                    innerRadius: 55,
                    paddingAngle: 1,
                    cornerRadius: 3,
                    valueFormatter: (v) => currency(v.value, moneyCode),
                    highlightScope: { faded: "global", highlighted: "item" },
                  },
                ]}
                height={280}
                margin={{ top: 10, bottom: 10, left: 10, right: 10 }}
                slotProps={{ legend: { hidden: true } }}
              />
            </ChartCard>
          </Stack>

          <ChartCard title="Income vs expenses by tag (top 12)" empty={netBars.labels.length === 0}>
            <BarChart
              layout="horizontal"
              height={Math.max(240, netBars.labels.length * 34 + 60)}
              yAxis={[{ scaleType: "band", data: netBars.labels, width: 110 }]}
              series={[
                { data: netBars.income, label: "Income", color: "#2e7d32", stack: "a" },
                { data: netBars.expense, label: "Expenses", color: "#d32f2f", stack: "a" },
              ]}
              margin={{ left: 120, right: 20, top: 20, bottom: 30 }}
              slotProps={{ legend: { position: { vertical: "top", horizontal: "right" } } }}
            />
          </ChartCard>

          <TagTable
            tags={tags}
            untagged={untagged}
            totals={totals}
            currencyCode={moneyCode}
          />
        </Stack>
      )}
    </Box>
  );
}

function formatDate(value, granularity) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  if (granularity === "year") return String(d.getFullYear());
  if (granularity === "quarter") {
    return `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}`;
  }
  if (granularity === "day" || granularity === "week") {
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

function compactCurrency(v) {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(v || 0);
}

function buildPie(tags, untagged, field) {
  const sign = field === "expense" ? -1 : 1;
  const items = tags
    .map((t) => ({ id: t.id, label: t.name, value: sign * t[field], color: t.color }))
    .filter((x) => x.value > 0.005)
    .sort((a, b) => b.value - a.value);

  const top = items.slice(0, 8);
  const rest = items.slice(8);
  if (rest.length) {
    top.push({
      id: "other",
      label: `Other (${rest.length})`,
      value: rest.reduce((s, x) => s + x.value, 0),
      color: OTHER_COLOR,
    });
  }
  const untaggedValue = untagged ? sign * untagged[field] : 0;
  if (untaggedValue > 0.005) {
    top.push({
      id: "untagged",
      label: "Untagged",
      value: untaggedValue,
      color: UNTAGGED_COLOR,
    });
  }
  return top;
}

function Kpi({ label, value, color }) {
  return (
    <Paper variant="outlined" sx={{ px: 3, py: 1.5, flex: 1, minWidth: 150 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" sx={{ color, fontWeight: 700 }}>
        {value}
      </Typography>
    </Paper>
  );
}

function ChartCard({ title, children, empty, action }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, flex: 1, minWidth: 0 }}>
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        sx={{ mb: 1 }}
      >
        <Typography variant="subtitle2" color="text.secondary">
          {title}
        </Typography>
        {action}
      </Stack>
      {empty ? (
        <Box sx={{ py: 6, textAlign: "center" }}>
          <Typography variant="body2" color="text.secondary">
            No data
          </Typography>
        </Box>
      ) : (
        children
      )}
    </Paper>
  );
}

function TagTable({ tags, untagged, totals, currencyCode = "EUR" }) {
  const rows = [...tags].sort((a, b) => a.net - b.net);
  const cell = { padding: "6px 12px", fontSize: 14 };
  const head = { ...cell, fontWeight: 600, color: "rgba(0,0,0,0.6)", textAlign: "right" };
  const money = (v, color) => (
    <td style={{ ...cell, textAlign: "right", color, fontWeight: 600 }}>
      {currency(v, currencyCode)}
    </td>
  );
  return (
    <Paper variant="outlined" sx={{ p: 2, overflowX: "auto" }}>
      <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 0.5 }}>
        Breakdown by tag
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        Each payment is counted once (split across its tags). Period totals are the ledger.
      </Typography>
      <Box component="table" sx={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <td style={{ ...head, textAlign: "left" }}>Tag</td>
            <td style={head}>Transactions</td>
            <td style={head}>Income</td>
            <td style={head}>Expenses</td>
            <td style={head}>Net</td>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <Box component="tr" key={t.id} sx={{ borderTop: "1px solid", borderColor: "divider" }}>
              <td style={cell}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Box
                    sx={{ width: 12, height: 12, borderRadius: "50%", bgcolor: t.color, flexShrink: 0 }}
                  />
                  {t.name}
                </Stack>
              </td>
              <td style={{ ...cell, textAlign: "right" }}>{t.count}</td>
              {money(t.income, "#2e7d32")}
              {money(t.expense, "#d32f2f")}
              {money(t.net, t.net < 0 ? "#d32f2f" : "#1a1a1a")}
            </Box>
          ))}
          {untagged && untagged.count > 0 && (
            <Box component="tr" sx={{ borderTop: "1px solid", borderColor: "divider" }}>
              <td style={{ ...cell, color: "rgba(0,0,0,0.6)" }}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Box
                    sx={{ width: 12, height: 12, borderRadius: "50%", bgcolor: UNTAGGED_COLOR, flexShrink: 0 }}
                  />
                  Untagged
                </Stack>
              </td>
              <td style={{ ...cell, textAlign: "right" }}>{untagged.count}</td>
              {money(untagged.income, "#2e7d32")}
              {money(untagged.expense, "#d32f2f")}
              {money(untagged.net)}
            </Box>
          )}
          {totals && (
            <Box component="tr" sx={{ borderTop: "2px solid", borderColor: "divider" }}>
              <td style={{ ...cell, fontWeight: 700 }}>Period</td>
              <td style={{ ...cell, textAlign: "right", fontWeight: 700 }}>
                {totals.count ?? 0}
              </td>
              {money(totals.income || 0, "#2e7d32")}
              {money(totals.expense || 0, "#d32f2f")}
              {money(totals.net || 0)}
            </Box>
          )}
        </tbody>
      </Box>
    </Paper>
  );
}
