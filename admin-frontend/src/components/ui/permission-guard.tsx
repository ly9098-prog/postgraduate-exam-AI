"use client";

import type { ReactNode } from "react";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission, type PermissionKey } from "@/lib/permissions/permissions";

type PermissionGuardProps = {
  permission?: PermissionKey;
  permissions?: PermissionKey[];
  matchAll?: boolean;
  fallback?: ReactNode;
  children: ReactNode;
};

export function PermissionGuard({
  permission,
  permissions,
  matchAll = false,
  fallback = null,
  children,
}: PermissionGuardProps) {
  const { permissions: userPermissions } = useAuthStore();

  const required = permission ? [permission] : permissions ?? [];

  const allowed =
    required.length === 0
      ? true
      : matchAll
        ? required.every((p) => hasPermission(userPermissions, p))
        : required.some((p) => hasPermission(userPermissions, p));

  if (!allowed) {
    return fallback ? <>{fallback}</> : null;
  }

  return <>{children}</>;
}

type PermissionGateProps = {
  permission: PermissionKey;
  fallback?: ReactNode;
  children: ReactNode;
};

export function PermissionGate({ permission, fallback = null, children }: PermissionGateProps) {
  return (
    <PermissionGuard permission={permission} fallback={fallback}>
      {children}
    </PermissionGuard>
  );
}

type SuperAdminGateProps = {
  fallback?: ReactNode;
  children: ReactNode;
};

export function SuperAdminGate({ fallback = null, children }: SuperAdminGateProps) {
  const { role } = useAuthStore();

  const isSuperAdmin = role?.name === "super_admin";

  if (!isSuperAdmin) {
    return fallback ? <>{fallback}</> : null;
  }

  return <>{children}</>;
}
