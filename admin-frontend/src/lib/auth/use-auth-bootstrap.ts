"use client";

import { useEffect, useRef } from "react";
import { useAuthStore } from "./auth-store";

export function useAuthBootstrap() {
  const bootstrap = useAuthStore((state) => state.bootstrap);
  const didBootstrap = useRef(false);

  useEffect(() => {
    if (didBootstrap.current) return;
    didBootstrap.current = true;
    void bootstrap();
  }, [bootstrap]);
}
