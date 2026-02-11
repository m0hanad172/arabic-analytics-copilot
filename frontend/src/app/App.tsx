import { useEffect } from "react";
import { AppShell } from "./layout/AppShell";

export function App() {
  useEffect(() => {
    const el = document.documentElement;
    el.setAttribute("dir", "rtl");
    el.setAttribute("lang", "ar");
    el.setAttribute("data-bs-theme", "dark");
  }, []);

  return <AppShell />;
}
