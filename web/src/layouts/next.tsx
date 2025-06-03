// modify by zwb for oracledb

import { ReactComponent as FileIcon } from '@/assets/svg/file-management.svg';
import { ReactComponent as GraphIcon } from '@/assets/svg/graph.svg';
import { ReactComponent as KnowledgeBaseIcon } from '@/assets/svg/knowledge-base.svg';
import { useTranslate } from '@/hooks/common-hooks';
import { useNavigateWithFromState } from '@/hooks/route-hook'; // 添加这行
import { Routes } from '@/routes';
import { MessageOutlined, SearchOutlined } from '@ant-design/icons';
import { Divider, Layout, Menu } from 'antd';
import { useMemo } from 'react';
import { Outlet, useLocation } from 'umi';
import styles from './index.less';
import { Header } from './next-header';
const { Sider, Content } = Layout;

export default function NextLayout() {
  const { t } = useTranslate('header');
  const { pathname } = useLocation();
  const navigate = useNavigateWithFromState(); // 添加这行

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
      {
        key: '/user',
        label: t('userManager'),
        icon: <FileIcon className="size-5" />,
        children: [
          { key: '/user/profile', label: t('profile') },
          { key: '/user/password', label: t('password') },
          { key: '/user/team', label: t('team') },
          { key: '/user/locale', label: t('setting') },
          { key: '/user/logout', label: t('logout') },
        ],
      },
      {
        key: '/system',
        label: t('systemManager'),
        icon: <FileIcon className="size-5" />,
        children: [
          { key: '/system/settingmodel', label: t('modelProvider') },
          { key: '/system/sysinfo', label: t('systeminfo') },
          { key: '/system/api', label: t('api') },
        ],
      },
    ],
    [t],
  );

  const selectedKey = useMemo(() => {
    const basePath = pathname.split('/')[1];
    const { logout } = useLogout();

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
            height: '100%',
            overflow: 'auto',
          }}
        >
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onSelect={({ key }) => navigate(key as Routes)} // 修改这行
            className="h-full pt-4"
          />
        </Sider>
        <Content
          style={{
            flex: 1,
            padding: '24px',
            overflow: 'auto',
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
