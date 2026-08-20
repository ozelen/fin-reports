import { Tab, Tabs } from "@mui/material";
import { useLocation, useNavigate } from "react-router-dom";

/** Secondary tabs under a section (My, Client, Transactions). */
export default function SubNav({ items }) {
  const location = useLocation();
  const navigate = useNavigate();
  // Prefer the longest matching prefix so /transactions/folders wins over /transactions.
  const value =
    items
      .map((t) => t.to)
      .filter(
        (to) =>
          location.pathname === to || location.pathname.startsWith(`${to}/`)
      )
      .sort((a, b) => b.length - a.length)[0] || items[0]?.to;

  return (
    <Tabs
      value={value}
      onChange={(_, v) => navigate(v)}
      sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}
    >
      {items.map((t) => (
        <Tab key={t.to} label={t.label} value={t.to} />
      ))}
    </Tabs>
  );
}
