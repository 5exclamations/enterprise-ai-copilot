"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { ApiError, fetchMe, keyStore } from "./api";
import type { Me } from "./types";

interface AuthCtx { me: Me | null; loading: boolean; error: string | null; login: (key: string) => Promise<void>; logout: () => void }
const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const key = keyStore.get();
    if (!key) { setLoading(false); return; }
    fetchMe(key).then(setMe).catch((e: ApiError) => { if (e.status === 401) keyStore.clear(); setError(e.message); }).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (key: string) => {
    setError(null);
    const user = await fetchMe(key.trim());
    keyStore.set(key.trim());
    setMe(user);
  }, []);
  const logout = useCallback(() => { keyStore.clear(); setMe(null); }, []);
  return <Ctx.Provider value={{ me, loading, error, login, logout }}>{children}</Ctx.Provider>;
}
