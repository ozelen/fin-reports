import axios from "axios";

const ACCESS_KEY = "is_access";
const REFRESH_KEY = "is_refresh";

export const tokenStore = {
  get access() {
    return localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY);
  },
  set({ access, refresh }) {
    if (access) localStorage.setItem(ACCESS_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const token = tokenStore.access;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshing = null;

function forceLogin() {
  tokenStore.clear();
  if (window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config || {};
    const status = error.response?.status;
    const url = String(original.url || "");
    const isAuthCall = url.includes("/auth/token/");

    if (status === 401 && !isAuthCall && !original._retry) {
      original._retry = true;
      if (tokenStore.refresh) {
        try {
          refreshing =
            refreshing ||
            axios.post("/api/auth/token/refresh/", { refresh: tokenStore.refresh });
          const { data } = await refreshing;
          refreshing = null;
          tokenStore.set({ access: data.access });
          original.headers = original.headers || {};
          original.headers.Authorization = `Bearer ${data.access}`;
          return api(original);
        } catch {
          refreshing = null;
        }
      }
      forceLogin();
    }
    return Promise.reject(error);
  },
);

export default api;
