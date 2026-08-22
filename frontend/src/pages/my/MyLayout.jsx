import { Box, Typography } from "@mui/material";
import { Outlet } from "react-router-dom";
import SubNav from "../../components/SubNav";

const ITEMS = [
  { label: "Details", to: "/my/details" },
  { label: "Accounts", to: "/my/accounts" },
  { label: "Documents", to: "/my/documents" },
  { label: "Bills", to: "/my/bills" },
];

export default function MyLayout() {
  return (
    <Box>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 1 }}>
        My
      </Typography>
      <SubNav items={ITEMS} />
      <Outlet />
    </Box>
  );
}
