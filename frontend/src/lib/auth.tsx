"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { account, ID } from "@/lib/appwrite";
import { authMessage } from "@/lib/auth-errors";
import { clearToken, SESSION_EXPIRED_EVENT } from "@/lib/token";

export interface SessionUser {
  id: string;
  email: string;
  name: string;
  emailVerified: boolean;
}

type Status = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: Status;
  user: SessionUser | null;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function toUser(u: { $id: string; email: string; name: string; emailVerification?: boolean }): SessionUser {
  return { id: u.$id, email: u.email, name: u.name, emailVerified: Boolean(u.emailVerification) };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ status: Status; user: SessionUser | null }>({
    status: "loading",
    user: null,
  });

  // Appwrite keeps the session (cookie or local storage), so a reload stays signed in.
  useEffect(() => {
    let cancelled = false;
    account
      .get()
      .then((u) => {
        if (!cancelled) setState({ status: "authenticated", user: toUser(u) });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "anonymous", user: null });
      });
    const onExpired = () => setState({ status: "anonymous", user: null });
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => {
      cancelled = true;
      window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    try {
      try {
        await account.createEmailPasswordSession({ email, password });
      } catch (e) {
        // A session already exists on this device: just continue with it.
        if ((e as { type?: string }).type !== "user_session_already_exists") throw e;
      }
      const u = await account.get();
      clearToken();
      setState({ status: "authenticated", user: toUser(u) });
    } catch (e) {
      throw new Error(authMessage(e));
    }
  }, []);

  const register = useCallback(
    async (name: string, email: string, password: string) => {
      try {
        await account.create({ userId: ID.unique(), email, password, name });
      } catch (e) {
        throw new Error(authMessage(e));
      }
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await account.deleteSession({ sessionId: "current" });
    } catch {
      // already signed out remotely: still clear local state
    }
    clearToken();
    setState({ status: "anonymous", user: null });
  }, []);

  const value = useMemo(
    () => ({ ...state, login, register, logout }),
    [state, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
