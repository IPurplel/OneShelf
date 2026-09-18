import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api } from "@/api/client";
import type { NotificationsResponse } from "@/api/types";

type NotificationState = {
  unseen: number;
  attention: number;
  refresh: () => Promise<void>;
};

const NotificationContext = createContext<NotificationState | null>(null);

export function NotificationProvider({ children, initial }: { children: ReactNode; initial?: { unseen: number; attention: number } }) {
  const [counts, setCounts] = useState(initial ?? { unseen: 0, attention: 0 });

  const refresh = useCallback(async () => {
    try {
      const payload = await api.get<NotificationsResponse>("/api/notifications");
      setCounts({ unseen: payload.unseen, attention: payload.attention });
    } catch {
      // A failed refresh leaves the last known counts alone rather than clearing the badge.
    }
  }, []);

  useEffect(() => {
    if (initial === undefined) void refresh();
  }, [initial, refresh]);

  const value = useMemo(() => ({ ...counts, refresh }), [counts, refresh]);
  return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>;
}

export function useNotifications(): NotificationState {
  const context = useContext(NotificationContext);
  if (context === null) throw new Error("useNotifications must be used inside NotificationProvider");
  return context;
}
