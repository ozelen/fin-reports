import { useEffect, useState } from "react";
import { Alert, Box, Button, Typography } from "@mui/material";
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
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>
        {client.name}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {[client.tax_id && `NIP ${client.tax_id}`, client.vat_mode, `${client.default_unit_price} ${client.currency}/h`]
          .filter(Boolean)
          .join(" · ")}
      </Typography>
      <SubNav items={items} />
      <Outlet context={{ client, setClient }} />
    </Box>
  );
}
