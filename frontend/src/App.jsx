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
import Budgets from "./pages/Budgets";
import Transactions from "./pages/Transactions";
import Folders from "./pages/Folders";
import Tags from "./pages/Tags";
import Rules from "./pages/Rules";
import Accounts from "./pages/Accounts";
import Clients from "./pages/Clients";
import Documents from "./pages/Documents";
import Invoices from "./pages/Invoices";
import Backup from "./pages/Backup";
import MyLayout from "./pages/my/MyLayout";
import MyDetails from "./pages/my/MyDetails";
import ClientLayout from "./pages/clients/ClientLayout";
import ClientDetails from "./pages/clients/ClientDetails";
import TransactionsLayout from "./pages/transactions/TransactionsLayout";

function RequireAuth({ children }) {
  const { isAuthed } = useAuth();
  return isAuthed ? children : <Navigate to="/login" replace />;
}

const TABS = [
  { label: "Dashboard", value: "/dashboard" },
  { label: "Budgets", value: "/budgets" },
  { label: "Transactions", value: "/transactions" },
  { label: "My", value: "/my" },
  { label: "Clients", value: "/clients" },
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
            variant="scrollable"
            scrollButtons="auto"
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
      <Route path="/budgets" element={<Protected><Budgets /></Protected>} />

      <Route path="/transactions" element={<Protected><TransactionsLayout /></Protected>}>
        <Route index element={<Transactions />} />
        <Route path="folders" element={<Folders />} />
        <Route path="tags" element={<Tags />} />
        <Route path="rules" element={<Rules />} />
      </Route>

      <Route path="/my" element={<Protected><MyLayout /></Protected>}>
        <Route index element={<Navigate to="details" replace />} />
        <Route path="details" element={<MyDetails />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="documents" element={<Documents />} />
      </Route>

      <Route path="/clients" element={<Protected><Clients /></Protected>} />
      <Route path="/clients/:clientId" element={<Protected><ClientLayout /></Protected>}>
        <Route index element={<Navigate to="details" replace />} />
        <Route path="details" element={<ClientDetails />} />
        <Route path="documents" element={<Documents />} />
        <Route path="invoices" element={<Invoices />} />
      </Route>

      <Route path="/upload" element={<Protected><UploadPage /></Protected>} />
      <Route path="/backup" element={<Protected><Backup /></Protected>} />

      {/* Legacy redirects */}
      <Route path="/accounts" element={<Navigate to="/my/accounts" replace />} />
      <Route path="/documents" element={<Navigate to="/my/documents" replace />} />
      <Route path="/invoices" element={<Navigate to="/clients" replace />} />
      <Route path="/folders" element={<Navigate to="/transactions/folders" replace />} />
      <Route path="/tags" element={<Navigate to="/transactions/tags" replace />} />
      <Route path="/rules" element={<Navigate to="/transactions/rules" replace />} />

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
