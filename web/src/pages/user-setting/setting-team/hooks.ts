import { useSetModalState, useShowDeleteConfirm } from '@/hooks/common-hooks';
import { useRegister } from '@/hooks/login-hooks';
import {
  useAddTenantUser,
  useAgreeTenant,
  useDeleteTenantUser,
  useFetchUserInfo,
} from '@/hooks/user-setting-hooks';
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateUserStatus } from '@/services/admin-service';
import { TenantRole } from '../constants';

export const useAddUser = () => {
  const { addTenantUser } = useAddTenantUser();
  const {
    visible: addingTenantModalVisible,
    hideModal: hideAddingTenantModal,
    showModal: showAddingTenantModal,
  } = useSetModalState();

  const handleAddUserOk = useCallback(
    async (email: string) => {
      const code = await addTenantUser(email);
      if (code === 0) {
        hideAddingTenantModal();
      }
    },
    [addTenantUser, hideAddingTenantModal],
  );

  return {
    addingTenantModalVisible,
    hideAddingTenantModal,
    showAddingTenantModal,
    handleAddUserOk,
  };
};

export const useHandleDeleteUser = () => {
  const { deleteTenantUser, loading } = useDeleteTenantUser();
  const showDeleteConfirm = useShowDeleteConfirm();
  const { t } = useTranslation();

  const handleDeleteTenantUser = (userId: string) => () => {
    showDeleteConfirm({
      title: t('setting.sureDelete'),
      onOk: async () => {
        const code = await deleteTenantUser({ userId });
        if (code === 0) {
        }
        return;
      },
    });
  };

  return { handleDeleteTenantUser, loading };
};

export const useHandleAgreeTenant = () => {
  const { agreeTenant } = useAgreeTenant();
  const { deleteTenantUser } = useDeleteTenantUser();
  const { data: user } = useFetchUserInfo();

  const handleAgree = (tenantId: string, isAgree: boolean) => () => {
    if (isAgree) {
      agreeTenant(tenantId);
    } else {
      deleteTenantUser({ tenantId, userId: user.id });
    }
  };

  return { handleAgree };
};

export const useHandleQuitUser = () => {
  const { deleteTenantUser, loading } = useDeleteTenantUser();
  const showDeleteConfirm = useShowDeleteConfirm();
  const { t } = useTranslation();

  const handleQuitTenantUser = (userId: string, tenantId: string) => () => {
    showDeleteConfirm({
      title: t('setting.sureQuit'),
      onOk: async () => {
        deleteTenantUser({ userId, tenantId });
      },
    });
  };

  return { handleQuitTenantUser, loading };
};


export const useUpdateUserStatus = () => {
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  const mutation = useMutation({
    mutationFn: ({ email, isActive }: { email: string; isActive: boolean }) =>
      updateUserStatus(email, isActive ? 'on' : 'off'),
    onSuccess: () => {
      // Invalidate user list queries to refresh the data
      queryClient.invalidateQueries({ queryKey: ['listTenantUser'] });
    },
    onError: (error) => {
      console.error('Failed to update user status:', error);
      // TODO: Show error notification
    },
  });

  return mutation;
};

export const useEditUser = () => {
  const {
    visible: editingUserModalVisible,
    hideModal: hideEditingUserModal,
    showModal: showEditingUserModal,
  } = useSetModalState();
  const [editingUser, setEditingUser] = useState<{
    user_id: string;
    nickname: string;
    email: string;
    role: TenantRole;
  } | null>(null);

  const handleEditUser = useCallback(
    (userData: { user_id: string; nickname: string; email: string; role: TenantRole }) => {
      setEditingUser(userData);
      showEditingUserModal();
    },
    [showEditingUserModal]
  );

  const handleEditUserOk = useCallback(
    async (data: { nickname: string; role: TenantRole }) => {
      // Note: Currently there's no API to update tenant user info
      // This is a placeholder for future implementation
      console.log('Would update user:', editingUser?.user_id, data);
      // TODO: Implement API call when available
      hideEditingUserModal();
      setEditingUser(null);
    },
    [editingUser, hideEditingUserModal]
  );

  return {
    editingUserModalVisible,
    hideEditingUserModal,
    showEditingUserModal: handleEditUser,
    handleEditUserOk,
    editingUser,
  };
};
