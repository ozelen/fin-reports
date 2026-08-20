import { Box, Typography } from "@mui/material";
import { Outlet } from "react-router-dom";
import SubNav from "../../components/SubNav";

const ITEMS = [
  { label: "All", to: "/transactions" },
  { label: "Folders", to: "/transactions/folders" },
  { label: "Tags", to: "/transactions/tags" },
  { label: "Rules", to: "/transactions/rules" },
];

export default function TransactionsLayout() {
  return (
    <Box>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 1 }}>
        Transactions
      </Typography>
      <SubNav items={ITEMS} />
      <Outlet />
    </Box>
  );
}
