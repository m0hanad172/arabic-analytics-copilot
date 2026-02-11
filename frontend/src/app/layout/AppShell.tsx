import { useState } from "react";
import { Topbar } from "./Topbar";
import { Sidebar } from "./Sidebar";
import { AskPage } from "../../features/ask/AskPage";

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="d-flex flex-column h-100">
      <Topbar onToggleSidebar={() => setSidebarOpen((v) => !v)} />
      <div className="container-fluid flex-grow-1 h-100">
        <div className="row h-100">
          <div
            className={`col-12 col-lg-3 col-xl-2 border-end p-0 h-100 ${
              sidebarOpen ? "" : "d-none d-lg-block"
            }`}
          >
            <Sidebar onCloseMobile={() => setSidebarOpen(false)} />
          </div>
          <div className="col-12 col-lg-9 col-xl-10 p-3 p-lg-4 h-100 overflow-auto">
            <AskPage />
          </div>
        </div>
      </div>
    </div>
  );
}
