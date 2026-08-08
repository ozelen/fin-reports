import { createContext, useContext, useMemo, useState } from "react";
import api, { tokenStore } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [isAuthed, setIsAuthed] = useState(Boolean(tokenStore.access));

  const value = useMemo(
    () => ({
      isAuthed,
      async login(username, password) {
        const { data } = await api.post("/auth/token/", { username, password });
        tokenStore.set({ access: data.access, refresh: data.refresh });
        setIsAuthed(true);
      },
      logout() {
        tokenStore.clear();
        setIsAuthed(false);
      },
    }),
    [isAuthed],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
