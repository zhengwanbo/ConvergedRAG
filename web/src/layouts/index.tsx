// /src/layouts/index.tsx
import { Divider, Layout, Menu, theme } from 'antd';
import React, { useMemo } from 'react'; // 添加 useMemo 导入
import { Outlet } from 'umi';
import '../locales/config';
import Header from './components/header';

import { Toaster as Sonner } from '@/components/ui/sonner';
import { Toaster } from '@/components/ui/toaster';

import { ReactComponent as FileIcon } from '@/assets/svg/file-management.svg';
import { ReactComponent as GraphIcon } from '@/assets/svg/graph.svg';
import { ReactComponent as KnowledgeBaseIcon } from '@/assets/svg/knowledge-base.svg';
import { useTranslate } from '@/hooks/common-hooks';
import { useNavigateWithFromState } from '@/hooks/route-hook';
import { MessageOutlined, SearchOutlined } from '@ant-design/icons';
import { useLocation } from 'umi';
import styles from './index.less';

const { Content, Sider } = Layout;

const App: React.FC = () => {
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken();
  const { t } = useTranslate('header');
  const navigate = useNavigateWithFromState();
  const { pathname } = useLocation();

  const menuItems = useMemo(
    () => [
      {
        key: '/knowledge',
        label: t('knowledgeBase'),
        icon: <KnowledgeBaseIcon className="size-5" />,
      },
      {
        key: '/chat',
        label: t('chat'),
        icon: <MessageOutlined className="size-5" />,
      },
      {
        key: '/search',
        label: t('search'),
        icon: <SearchOutlined className="size-5" />,
      },
      {
        key: '/flow',
        label: t('flow'),
        icon: <GraphIcon className="size-5" />,
      },
      {
        key: '/file',
        label: t('fileManager'),
        icon: <FileIcon className="size-5" />,
      },
    ],
    [t],
  );

  const selectedKey = useMemo(() => {
    return (
      menuItems.find((item) => pathname.startsWith(item.key))?.key ||
      '/knowledge'
    );
  }, [pathname, menuItems]);

  return (
    <Layout className={styles.layout}>
      {/* Header 放在最上方 */}
      <Header />

      {/* 添加分界线 */}
      <Divider orientationMargin={0} className={styles.divider} />

      {/* 下方使用新的 Layout 包含 Sider 和 Content */}
      <Layout style={{ display: 'flex', minHeight: 'calc(100vh - 72px)' }}>
        <Sider
          width={200}
          style={{
            background: colorBgContainer,
            height: '100%',
            overflow: 'auto',
          }}
        >
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onSelect={({ key }) => navigate(key)}
            style={{ height: '100%', borderRight: 0 }}
          />
        </Sider>

        <Content
          style={{
            flex: 1,
            padding: '24px',
            background: colorBgContainer,
            overflow: 'auto',
          }}
        >
          <Outlet />
        </Content>
      </Layout>

      <Toaster />
      <Sonner position={'top-right'} expand richColors closeButton />
    </Layout>
  );
};

export default App;
