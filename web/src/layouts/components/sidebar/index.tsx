import { useTranslate } from '@/hooks/common-hooks';
import { useNavigateWithFromState } from '@/hooks/route-hook';
import { useLogout } from '@/hooks/use-login-request';
import { useFetchUserInfo } from '@/hooks/use-user-setting-request';
import { cn } from '@/lib/utils';
import { Routes } from '@/routes';
import {
  Bot,
  Cable,
  ChevronDown,
  ChevronRight,
  Database,
  Files,
  FolderKanban,
  House,
  Library,
  LogOut,
  type LucideIcon,
  MessageSquareText,
  Search,
  Settings2,
  UserCog,
  Users,
  Users2,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router';
import styles from './index.module.less';

type SidebarProps = {
  collapsed?: boolean;
};

type NavItem = {
  key: string;
  label: string;
  icon: LucideIcon;
  path: string;
  matchers: string[];
};

export default function Sidebar({ collapsed = false }: SidebarProps) {
  const navigate = useNavigateWithFromState();
  const { pathname } = useLocation();
  const { t } = useTranslate('header');
  const { t: settingT } = useTranslate('setting');
  const { logout } = useLogout();
  const { data: userInfo } = useFetchUserInfo();
  const [systemOpen, setSystemOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);

  const mainItems = useMemo<NavItem[]>(
    () => [
      {
        key: 'home',
        label: t('home'),
        icon: House,
        path: Routes.Root,
        matchers: [Routes.Root, Routes.Home],
      },
      {
        key: 'agents',
        label: t('flow'),
        icon: Bot,
        path: Routes.Agents,
        matchers: [
          Routes.Agents,
          Routes.Agent,
          Routes.AgentTemplates,
          Routes.AgentLogPage,
        ],
      },
      {
        key: 'datasets',
        label: t('dataset'),
        icon: Library,
        path: Routes.Datasets,
        matchers: [Routes.Datasets, Routes.DatasetBase],
      },
      {
        key: 'chats',
        label: t('chat'),
        icon: MessageSquareText,
        path: Routes.Chats,
        matchers: [Routes.Chats, Routes.Chat],
      },
      {
        key: 'searches',
        label: t('search'),
        icon: Search,
        path: Routes.Searches,
        matchers: [Routes.Searches, Routes.Search],
      },
      {
        key: 'memories',
        label: t('memories'),
        icon: FolderKanban,
        path: Routes.Memories,
        matchers: [Routes.Memories, Routes.Memory],
      },
      {
        key: 'files',
        label: t('fileManager'),
        icon: Files,
        path: Routes.Files,
        matchers: [Routes.Files],
      },
    ],
    [t],
  );

  const settingItems = useMemo<NavItem[]>(
    () => [
      {
        key: 'data-source',
        label: settingT('dataSources'),
        icon: Database,
        path: `${Routes.UserSetting}${Routes.DataSource}`,
        matchers: [`${Routes.UserSetting}${Routes.DataSource}`],
      },
      {
        key: 'model',
        label: settingT('model'),
        icon: UserCog,
        path: `${Routes.UserSetting}${Routes.Model}`,
        matchers: [`${Routes.UserSetting}${Routes.Model}`],
      },
      {
        key: 'mcp',
        label: 'MCP',
        icon: Cable,
        path: `${Routes.UserSetting}${Routes.Mcp}`,
        matchers: [`${Routes.UserSetting}${Routes.Mcp}`],
      },
      {
        key: 'api',
        label: settingT('api'),
        icon: Cable,
        path: `${Routes.UserSetting}${Routes.Api}`,
        matchers: [`${Routes.UserSetting}${Routes.Api}`],
      },
    ],
    [settingT],
  );

  const profileItems = useMemo<NavItem[]>(
    () => [
      {
        key: 'profile',
        label: settingT('overview'),
        icon: UserCog,
        path: `${Routes.UserSetting}${Routes.Profile}`,
        matchers: [`${Routes.UserSetting}${Routes.Profile}`],
      },
      {
        key: 'team',
        label: settingT('team'),
        icon: Users,
        path: `${Routes.UserSetting}${Routes.Team}`,
        matchers: [`${Routes.UserSetting}${Routes.Team}`],
      },
      ...(userInfo?.is_superuser
        ? [
            {
              key: 'manage-users',
              label: settingT('manageUsers'),
              icon: Users2,
              path: `${Routes.UserSetting}/manage-users`,
              matchers: [`${Routes.UserSetting}/manage-users`],
            } satisfies NavItem,
          ]
        : []),
    ],
    [settingT, userInfo?.is_superuser],
  );

  useEffect(() => {
    setSystemOpen(
      settingItems.some((item) =>
        item.matchers.some((matcher) => pathname.startsWith(matcher)),
      ),
    );
    setUserOpen(
      profileItems.some((item) =>
        item.matchers.some((matcher) => pathname.startsWith(matcher)),
      ),
    );
  }, [pathname, profileItems, settingItems]);

  const renderItem = (item: NavItem) => {
    const Icon = item.icon;
    const active = item.matchers.some((matcher) =>
      pathname.startsWith(matcher),
    );

    return (
      <button
        key={item.key}
        type="button"
        onClick={() => navigate(item.path)}
        className={cn(
          'flex w-full items-center rounded-xl px-3 py-3 text-left transition-colors',
          'hover:bg-bg-card hover:text-text-primary',
          active
            ? 'bg-bg-card text-text-primary shadow-[inset_0_0_0_1px_var(--border-default)]'
            : 'text-text-secondary',
          collapsed ? 'justify-center' : 'gap-3',
        )}
        title={collapsed ? item.label : undefined}
      >
        <Icon className="h-5 w-5 shrink-0" />
        {!collapsed && (
          <span className="truncate text-sm font-medium">{item.label}</span>
        )}
      </button>
    );
  };

  const renderGroup = (
    title: string,
    Icon: LucideIcon,
    items: NavItem[],
    open: boolean,
    onToggle: () => void,
  ) => {
    const ArrowIcon = open ? ChevronDown : ChevronRight;

    return (
      <section className="mt-6">
        {!collapsed && (
          <button
            type="button"
            onClick={onToggle}
            className="flex w-full items-center justify-between rounded-xl px-3 py-3 text-left text-text-primary transition-colors hover:bg-bg-card"
          >
            <span className="flex items-center gap-3">
              <Icon className="h-5 w-5 shrink-0" />
              <span className="truncate text-sm font-medium">{title}</span>
            </span>
            <ArrowIcon className="h-4 w-4 shrink-0 text-text-secondary" />
          </button>
        )}
        {(open || collapsed) && (
          <div className={cn('space-y-2', collapsed ? 'mt-0' : 'mt-2')}>
            {items.map(renderItem)}
          </div>
        )}
      </section>
    );
  };

  return (
    <aside
      className={cn(
        styles.sidebar,
        'fixed left-0 top-[60px] z-40 h-[calc(100dvh-60px)] transition-[width] duration-200',
        collapsed ? 'w-[88px]' : 'w-64',
      )}
    >
      <div
        className={cn(
          styles.scrollArea,
          'flex h-full flex-col overflow-y-auto px-3 py-4',
        )}
      >
        <section className="space-y-2">{mainItems.map(renderItem)}</section>

        {renderGroup(
          settingT('systemSettings'),
          Settings2,
          settingItems,
          systemOpen,
          () => setSystemOpen((value) => !value),
        )}

        {renderGroup(
          settingT('userManagement'),
          Users2,
          profileItems,
          userOpen,
          () => setUserOpen((value) => !value),
        )}

        <section className="mt-auto pt-6">
          <button
            type="button"
            onClick={() => logout()}
            className={cn(
              'flex w-full items-center rounded-xl px-3 py-3 text-left transition-colors',
              'border border-border-default text-text-secondary hover:bg-bg-card hover:text-text-primary',
              collapsed ? 'justify-center' : 'gap-3',
            )}
            title={collapsed ? settingT('logout') : undefined}
          >
            <LogOut className="h-5 w-5 shrink-0" />
            {!collapsed && (
              <span className="truncate text-sm font-medium">
                {settingT('logout')}
              </span>
            )}
          </button>
        </section>
      </div>
    </aside>
  );
}
