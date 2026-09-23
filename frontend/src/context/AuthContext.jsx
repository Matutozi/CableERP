import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, AUTH_EXPIRED_EVENT } from "../services/api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // undefined while the session check is in flight, null when signed out.
  const [user, setUser] = useState(undefined);

  const refresh = useCallback(() => api.me().then((data) => setUser(data.user)), []);

  useEffect(() => {
    refresh().catch(() => setUser(null));
    const onExpired = () => setUser(null);
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, [refresh]);

  const value = useMemo(
    () => ({
      user,
      refresh,
      login: async (credentials) => setUser((await api.login(credentials)).user),
      register: async (details) => setUser((await api.register(details)).user),
      logout: async () => {
        try {
          await api.logout();
        } finally {
          setUser(null);
        }
      },
      signOutEverywhere: async () => {
        try {
          await api.logoutEverywhere();
        } finally {
          setUser(null);
        }
      },
    }),
    [user, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// The hook belongs beside the context it reads. Splitting it into its own module would
// satisfy fast refresh but scatter one small concern across two files for no other gain.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  return useContext(AuthContext);
}
