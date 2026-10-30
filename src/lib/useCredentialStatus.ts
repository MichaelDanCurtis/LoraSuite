import { useEffect, useState } from "react";

import {
  getCredentialStatus,
  subscribeToCredentialChanges,
  type CredentialId,
} from "./credentials";

export function useCredentialStatus(id: CredentialId | undefined): boolean {
  const [stored, setStored] = useState(false);

  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      if (!id) {
        setStored(false);
        return;
      }
      try {
        const status = await getCredentialStatus(id);
        if (!disposed) setStored(status.stored);
      } catch {
        if (!disposed) setStored(false);
      }
    };
    void refresh();
    const unsubscribe = subscribeToCredentialChanges((changedId) => {
      if (changedId === id) void refresh();
    });
    return () => {
      disposed = true;
      unsubscribe();
    };
  }, [id]);

  return stored;
}
