"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { Spinner } from "@/components/ui";

export default function Home() {
  const { me, loading } = useAuth();
  const router = useRouter();
  useEffect(() => { if (!loading) router.replace(me ? "/chat" : "/login"); }, [me, loading, router]);
  return <div style={{ display: "grid", placeItems: "center", height: "100vh" }}><Spinner /></div>;
}
