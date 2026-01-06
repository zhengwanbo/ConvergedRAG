import { Layout, theme } from 'antd';
import React, { useState } from 'react';
import { Outlet } from 'umi';
import Sidebar from './components/sidebar';
import { Header } from './next-header';

const { Content } = Layout;

export default function NextLayout() {
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const handleSidebarCollapse = (collapsed: boolean) => {
    setSidebarCollapsed(collapsed);
  };

  const sidebarWidth = sidebarCollapsed ? 80 : 240;
  const contentMarginLeft = sidebarCollapsed ? 80 : 240;

  return (
    <Layout style={{ minHeight: '100vh', paddingTop: '61px' }}>
      <Header />
      <Layout>
        <Sidebar onCollapseChange={handleSidebarCollapse} />
        <Layout style={{ marginLeft: contentMarginLeft, transition: 'margin-left 0.2s' }}>
          <Content
            style={{
              minHeight: 'calc(100vh - 61px)',
              background: colorBgContainer,
              borderRadius: borderRadiusLG,
              overflow: 'auto',
              padding: '24px',
              margin: '8px',
              marginTop: '0',
              width: '100%',
              boxSizing: 'border-box',
              transition: 'all 0.2s',
            }}
          >
            <Outlet />
          </Content>
        </Layout>
      </Layout>
    </Layout>
  );
}
