import { useEffect, useState } from "react";
import { Alert, Box, Button, Chip, Stack, Typography } from "@mui/material";
import { Link as RouterLink, Outlet, useParams } from "react-router-dom";
import SubNav from "../../components/SubNav";
import api from "../../api";

export default function ClientLayout() {
  const { clientId } = useParams();
  const [client, setClient] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setClient(null);
    setError("");
    api
      .get(`/clients/${clientId}/`)
      .then(({ data }) => {
        if (!cancelled) setClient(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e.response?.data?.detail || "Client not found");
      });
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  if (error) {
    return (
      <Box>
        <Alert
          severity="error"
          action={
            <Button component={RouterLink} to="/clients" color="inherit" size="small">
              Back to clients
            </Button>
          }
        >
          {error}
        </Alert>
      </Box>
    );
  }

  if (!client) return null;

  const base = `/clients/${clientId}`;
  const items = [
    { label: "Details", to: `${base}/details` },
    { label: "Documents", to: `${base}/documents` },
    { label: "Invoices", to: `${base}/invoices` },
  ];

  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          {client.name}
        </Typography>
        <Chip
          size="small"
          color={client.is_active ? "success" : "default"}
          label={client.is_active ? "Active" : "Inactive"}
        />
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {[
          client.tax_id && `NIP ${client.tax_id}`,
          client.vat_mode,
          `${client.default_unit_price} ${client.currency}/${client.billing_unit === "day" ? "day" : "h"}`,
        ]
          .filter(Boolean)
          .join(" · ")}
      </Typography>
      <SubNav items={items} />
      <Outlet context={{ client, setClient }} />
    </Box>
  );
}
