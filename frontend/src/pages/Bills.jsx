import { useEffect, useState } from "react";
import { Alert, Box, Chip, Paper, Stack, Typography } from "@mui/material";
import ReceiptLongIcon from "@mui/icons-material/ReceiptLong";
import api from "../api";
import ReceiptDialog from "../components/ReceiptDialog";
import { money } from "../money";

const STATUS = {
  paid: { color: "success", label: "Paid" },
  overdue: { color: "error", label: "Overdue" },
  unpaid: { color: "warning", label: "Unpaid" },
};

export default function Bills() {
  const [bills, setBills] = useState([]);
  const [error, setError] = useState("");
  const [receiptId, setReceiptId] = useState(null);
  const [tags, setTags] = useState([]);

  const load = async () => {
    const { data } = await api.get("/receipts/", {
      params: { kind: "invoice", page_size: 200 },
    });
    setBills(data.results || data);
  };

  useEffect(() => {
    load().catch((e) => setError(e.response?.data?.detail || e.message));
    api
      .get("/tags/", { params: { page_size: 200 } })
      .then(({ data }) => setTags(data.results || data))
      .catch(() => {});
  }, []);

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}
      <Stack spacing={1}>
        {bills.map((bill) => {
          const st = STATUS[bill.status] || STATUS.unpaid;
          return (
            <Paper
              key={bill.id}
              variant="outlined"
              sx={{ p: 1.5, display: "flex", alignItems: "center", gap: 2, cursor: "pointer" }}
              onClick={() => setReceiptId(bill.id)}
            >
              <ReceiptLongIcon color="action" />
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                  <Typography sx={{ fontWeight: 600 }}>
                    {bill.merchant || bill.original_filename || `Invoice #${bill.id}`}
                  </Typography>
                  <Chip size="small" color={st.color} label={st.label} />
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  {[bill.document_date, money(bill.amount, bill.currency)]
                    .filter(Boolean)
                    .join(" · ")}
                </Typography>
              </Box>
            </Paper>
          );
        })}
        {bills.length === 0 && (
          <Typography color="text.secondary">
            No incoming invoices yet. Send a factura PDF on Telegram and it lands here.
          </Typography>
        )}
      </Stack>
      <ReceiptDialog
        receiptId={receiptId}
        allTags={tags}
        onClose={() => setReceiptId(null)}
        onSaved={load}
      />
    </Box>
  );
}
