import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import api from "../../api";

const BLANK = {
  legal_name: "",
  trade_name: "",
  vat_number: "",
  address: "",
  city: "",
  country: "Spain",
  phone: "",
  email: "",
  legal_form: "Private Entrepreneur | Autónomo",
};

const FIELDS = [
  ["legal_name", "Legal name", false],
  ["trade_name", "Trade name", false],
  ["vat_number", "VAT number", false],
  ["legal_form", "Legal form", false],
  ["phone", "Phone", false],
  ["email", "Email", false],
  ["address", "Address", true],
  ["city", "City", false],
  ["country", "Country", false],
];

export default function MyDetails() {
  const [form, setForm] = useState(BLANK);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get("/issuer/")
      .then(({ data }) => {
        if (data) setForm({ ...BLANK, ...data });
      })
      .catch((e) => setError(e.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    setError("");
    setSaved(false);
    try {
      const { data } = await api.put("/issuer/", form);
      setForm({ ...BLANK, ...data });
      setSaved(true);
    } catch (e) {
      setError(e.response?.data?.detail || JSON.stringify(e.response?.data) || e.message);
    }
  };

  if (loading) return null;

  return (
    <Box maxWidth={560}>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Your issuer details are snapshotted onto invoices when they are issued.
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}
      {saved && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
          Saved.
        </Alert>
      )}
      <Stack spacing={2}>
        {FIELDS.map(([key, label, multiline]) => (
          <TextField
            key={key}
            label={label}
            value={form[key] || ""}
            onChange={(e) => setForm({ ...form, [key]: e.target.value })}
            fullWidth
            multiline={multiline}
            minRows={multiline ? 2 : 1}
            required={key === "legal_name"}
          />
        ))}
        <Box>
          <Button
            variant="contained"
            onClick={save}
            disabled={!form.legal_name.trim()}
          >
            Save details
          </Button>
        </Box>
      </Stack>
    </Box>
  );
}
