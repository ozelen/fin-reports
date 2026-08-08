import { useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Divider,
  Stack,
  Typography,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import RestoreIcon from "@mui/icons-material/Restore";
import api from "../api";

export default function Backup() {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState(null);
  const [error, setError] = useState("");

  const download = async () => {
    setBusy("export");
    setError("");
    setMessage(null);
    try {
      const res = await api.get("/backup/export/", { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `income-share-backup-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("Backup download failed.");
    } finally {
      setBusy("");
    }
  };

  const restore = async (file) => {
    if (!file) return;
    if (
      !window.confirm(
        "Restoring will REPLACE all of your current accounts, transactions, tags, rules and folders with the backup contents. Continue?",
      )
    ) {
      return;
    }
    setBusy("import");
    setError("");
    setMessage(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const { data } = await api.post("/backup/import/", form);
      const parts = Object.entries(data.restored || {})
        .map(([k, v]) => `${v} ${k}`)
        .join(", ");
      setMessage(`Restore complete: ${parts || "no records"}.`);
    } catch (err) {
      setError(err.response?.data?.detail || "Restore failed.");
    } finally {
      setBusy("");
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <Box>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>
        Backup &amp; restore
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}
      {message && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMessage(null)}>
          {message}
        </Alert>
      )}

      <Card variant="outlined" sx={{ maxWidth: 640 }}>
        <CardContent>
          <Stack spacing={1}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              Export
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Download a JSON snapshot of all your accounts, transactions, tags,
              rules and folders. Keep it somewhere safe.
            </Typography>
            <Box>
              <Button
                variant="contained"
                startIcon={busy === "export" ? <CircularProgress size={18} /> : <DownloadIcon />}
                onClick={download}
                disabled={Boolean(busy)}
              >
                Download backup
              </Button>
            </Box>
          </Stack>

          <Divider sx={{ my: 3 }} />

          <Stack spacing={1}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              Restore
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Import a backup file. This replaces all of your current data with the
              backup contents.
            </Typography>
            <Box>
              <Button
                variant="outlined"
                color="warning"
                startIcon={busy === "import" ? <CircularProgress size={18} /> : <RestoreIcon />}
                onClick={() => inputRef.current?.click()}
                disabled={Boolean(busy)}
              >
                Restore from file
              </Button>
              <input
                ref={inputRef}
                type="file"
                accept=".json,application/json"
                hidden
                onChange={(e) => restore(e.target.files?.[0])}
              />
            </Box>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
