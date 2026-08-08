import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import {
  AppBar,
  Box,
  Button,
  Container,
  Tab,
  Tabs,
  Toolbar,
  Typography,
} from "@mui/material";
import { useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import UploadPage from "./pages/Upload";
import Dashboard from "./pages/Dashboard";
import Transactions from "./pages/Transactions";
import Folders from "./pages/Folders";
import Tags from "./pages/Tags";
import Rules from "./pages/Rules";
import Accounts from "./pages/Accounts";
import Clients from "./pages/Clients";
import Documents from "./pages/Documents";
import Invoices from "./pages/Invoices";
import Backup from "./pages/Backup";

function RequireAuth({ children }) {
  const { isAuthed } = useAuth();
  return isAuthed ? children : <Navigate to="/login" replace />;
}

const TABS = [
  { label: "Dashboard", value: "/dashboard" },
  { label: "Transactions", value: "/transactions" },
  { label: "Folders", value: "/folders" },
  { label: "Tags", value: "/tags" },
  { label: "Rules", value: "/rules" },
  { label: "Accounts", value: "/accounts" },
  { label: "Clients", value: "/clients" },
  { label: "Documents", value: "/documents" },
  { label: "Invoices", value: "/invoices" },
  { label: "Upload", value: "/upload" },
  { label: "Backup", value: "/backup" },
];

function Shell({ children }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const tab =
    TABS.map((t) => t.value).find((v) => location.pathname.startsWith(v)) ||
    "/dashboard";

  return (
    <Box>
      <AppBar position="static" elevation={0}>
        <Toolbar>
          <Typography variant="h6" sx={{ fontWeight: 700, mr: 4 }}>
            Income Share
          </Typography>
          <Tabs
            value={tab}
            onChange={(_, v) => navigate(v)}
            textColor="inherit"
            indicatorColor="secondary"
            sx={{ flexGrow: 1 }}
          >
            {TABS.map((t) => (
              <Tab key={t.value} label={t.label} value={t.value} />
            ))}
          </Tabs>
          <Button
            color="inherit"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            Logout
          </Button>
        </Toolbar>
      </AppBar>
      <Container maxWidth="xl" sx={{ py: 3 }}>
        {children}
      </Container>
    </Box>
  );
}

function Protected({ children }) {
  return (
    <RequireAuth>
      <Shell>{children}</Shell>
    </RequireAuth>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
      <Route path="/transactions" element={<Protected><Transactions /></Protected>} />
      <Route path="/folders" element={<Protected><Folders /></Protected>} />
      <Route path="/tags" element={<Protected><Tags /></Protected>} />
      <Route path="/rules" element={<Protected><Rules /></Protected>} />
      <Route path="/accounts" element={<Protected><Accounts /></Protected>} />
      <Route path="/clients" element={<Protected><Clients /></Protected>} />
      <Route path="/documents" element={<Protected><Documents /></Protected>} />
      <Route path="/invoices" element={<Protected><Invoices /></Protected>} />
      <Route path="/upload" element={<Protected><UploadPage /></Protected>} />
      <Route path="/backup" element={<Protected><Backup /></Protected>} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
