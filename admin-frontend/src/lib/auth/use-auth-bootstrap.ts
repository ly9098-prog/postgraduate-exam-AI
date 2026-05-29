"use client";

import { useEffect } from "react";
import { useAuthStore } from "./auth-store";

export function useAuthBootstrap() {
  const bootstrap = useAuthStore((state) => state.bootstrap);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);
}
