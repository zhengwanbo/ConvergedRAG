import { theme } from 'antd';
import { useState } from 'react';
import { Outlet } from 'react-router';
import Sidebar from './components/sidebar';
import { Header } from './next-header';

export default function NextLayout() {
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken();
  const [collapsed, setCollapsed] = useState(false);

  const sidebarWidth = collapsed ? 88 : 256;

  return (
    <main
      className="h-dvh overflow-hidden"
      style={{ background: 'var(--bg-base, #0f1115)' }}
    >
      <Header
        collapsed={collapsed}
        onToggleSidebar={() => setCollapsed((v) => !v)}
      />
      <div className="h-full pt-[60px]">
        <Sidebar collapsed={collapsed} />
        <section
          className="h-[calc(100dvh-60px)] overflow-auto p-2 transition-[margin] duration-200"
          style={{ marginLeft: sidebarWidth }}
        >
          <div
            className="min-h-[calc(100dvh-76px)] overflow-hidden"
            style={{
              background: colorBgContainer,
              borderRadius: borderRadiusLG,
              padding: 24,
            }}
          >
            <Outlet />
          </div>
        </section>
      </div>
    </main>
  );
}
