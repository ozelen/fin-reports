import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import api from "../api";

export default function UploadPage() {
  const inputRef = useRef(null);
  const navigate = useNavigate();
  const [dragActive, setDragActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState("");

  useEffect(() => {
    api.get("/accounts/", { params: { page_size: 200 } }).then(({ data }) => {
      setAccounts(data.results);
      const def = data.results.find((a) => a.is_default) || data.results[0];
      if (def) setAccountId(def.id);
    });
  }, []);

  const handleFile = async (file) => {
    if (!file) return;
    setBusy(true);
    setError("");
    setResult(null);
    const form = new FormData();
    form.append("file", file);
    if (accountId) form.append("account", accountId);
    try {
      const { data } = await api.post("/uploads/", form);
      setResult(data);
    } catch (err) {
      setError(err.response?.data?.detail || "Upload failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>
        Upload a statement
      </Typography>

      {accounts.length > 0 ? (
        <TextField
          select
          label="Import into account"
          size="small"
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          sx={{ minWidth: 260, mb: 2 }}
        >
          {accounts.map((a) => (
            <MenuItem key={a.id} value={a.id}>
              {a.name}
              {a.is_default ? " (default)" : ""}
            </MenuItem>
          ))}
        </TextField>
      ) : (
        <Alert severity="info" sx={{ mb: 2 }}>
          No accounts yet. Create one on the Accounts page to organise imports by
          account.
        </Alert>
      )}
      <Card
        variant="outlined"
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          handleFile(e.dataTransfer.files?.[0]);
        }}
        sx={{
          borderStyle: "dashed",
          borderWidth: 2,
          borderColor: dragActive ? "primary.main" : "divider",
          bgcolor: dragActive ? "action.hover" : "background.paper",
          cursor: "pointer",
        }}
        onClick={() => inputRef.current?.click()}
      >
        <CardContent sx={{ textAlign: "center", py: 6 }}>
          {busy ? (
            <CircularProgress />
          ) : (
            <>
              <CloudUploadIcon sx={{ fontSize: 48, color: "text.secondary" }} />
              <Typography sx={{ mt: 1 }}>
                Drag &amp; drop a bank statement here, or click to browse
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Supported: .xls, .xlsx, .csv
              </Typography>
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept=".xls,.xlsx,.csv"
            hidden
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </CardContent>
      </Card>

      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}

      {result && (
        <Alert severity="success" sx={{ mt: 2 }}>
          <Stack spacing={0.5}>
            <Typography>
              Imported <strong>{result.imported_count}</strong> transactions
              {result.skipped_duplicates > 0 &&
                ` (${result.skipped_duplicates} duplicates skipped)`}
              .
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {result.account_holder} · {result.account_iban} · {result.currency}
            </Typography>
            <Box sx={{ mt: 1 }}>
              <Button size="small" variant="contained" onClick={() => navigate("/transactions")}>
                View transactions
              </Button>
            </Box>
          </Stack>
        </Alert>
      )}
    </Box>
  );
}
