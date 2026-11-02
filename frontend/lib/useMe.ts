"use client";
import { useEffect, useState } from "react";
import { api, Me } from "./api";

export function useMe() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api<Me>("/auth/me").then(setMe).catch(() => setMe(null)).finally(() => setLoading(false));
  }, []);
  return { me, loading };
}
