import { useTranslate } from '@/hooks/common-hooks';
import { useNavigateWithFromState } from '@/hooks/route-hook'; // 添加这行
import { Routes } from '@/routes';
import { Layout, Menu } from 'antd';
import { Cpu, File, Library, MessageSquareText, Search } from 'lucide-react';
import { useMemo } from 'react';
import { Outlet, useLocation } from 'umi';
import { Header } from './next-header';

const { Sider, Content } = Layout;

export default function NextLayout() {
  const { t } = useTranslate('header');
  const { pathname } = useLocation();
  const navigate = useNavigateWithFromState(); // 添加这行

  const menuItems = useMemo(
    () => [
      {
        key: Routes.Datasets,
        label: t('knowledgeBase'),
        icon: <Library className="size-5" />,
      },
      {
        key: Routes.Chats,
        label: t('chat'),
        icon: <MessageSquareText className="size-5" />,
      },
      {
        key: Routes.Searches,
        label: t('search'),
        icon: <Search className="size-5" />,
      },
      {
        key: Routes.Agents,
        label: t('flow'),
        icon: <Cpu className="size-5" />,
      },
      {
        key: Routes.Files,
        label: t('fileManager'),
        icon: <File className="size-5" />,
      },
    ],
    [t],
  );

  const selectedKey = useMemo(() => {
    return (
      menuItems.find((item) => pathname.startsWith(item.key))?.key ||
      Routes.Home
    );
  }, [pathname, menuItems]);

  return (
    <Layout className="h-full flex flex-col text-colors-text-neutral-strong">
      <Sider width={200} theme="light">
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onSelect={({ key }) => navigate(key as Routes)} // 修改这行
          className="h-full pt-4"
        />
      </Sider>
      <Layout>
        <Header />
        <Content className="overflow-auto">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
