import { Layout, theme } from 'antd';
import React, { useState } from 'react';
import { Outlet } from 'umi';
import '../locales/config';
import Sidebar from './components/sidebar';
import { Header } from './next-header';

import styles from './index.less';

const { Content } = Layout;

const App: React.FC = () => {
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
              minHeight: 'calc(100vh - 60px)',
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
};

export default App;
