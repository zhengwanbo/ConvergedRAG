import { useFetchUserInfo } from '@/hooks/use-user-setting-request';
import AdminUserManagement from '@/pages/admin/users';
import { useTranslation } from 'react-i18next';

export default function ManageUsers() {
  const { data: userInfo, loading } = useFetchUserInfo();
  const { t } = useTranslation();

  if (loading) {
    return <div className="p-6 text-text-secondary">{t('common.loading')}</div>;
  }

  if (!userInfo?.is_superuser) {
    return (
      <div className="p-6 text-text-secondary">
        {t('setting.manageUsersForbidden')}
      </div>
    );
  }

  return (
    <AdminUserManagement
      allowDetailNavigation={false}
      titleKey="setting.manageUsers"
    />
  );
}
